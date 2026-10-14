# -*- coding: utf-8 -*-
"""
早报工作台 · 网页后台（端口 12345）
========================================
提供网页配置界面 + REST API + 内置定时调度（APScheduler），取代 Docker 中的 cron。

启动：
  python src/admin_app.py            # 默认 0.0.0.0:12345
  ADMIN_PORT=12345 python src/admin_app.py
  ADMIN_PASSWORD=xxx  python src/admin_app.py   # 开启简单口令保护（可选）

功能：
  - 网页配置：基础/内容源/推送渠道(含钉钉)/定时/接收者/过滤/运维
  - 配置落 config.json，即时生效（apply_overrides）
  - 定时调度：按配置的时间每日触发 run_once（含 365 未发稿的重试）
  - 手动"立即生成并推送"、单通道"测试推送"、日志与状态查看
"""
import os
import sys
import json
import datetime
import threading

# 让 src 内模块可被 import（无论从哪启动）
BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from flask import Flask, request, jsonify, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import config as cfg
from config_store import load_config, save_config, apply_overrides
import main as main_mod
import wechat_sender as ws

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True   # 改 admin.html 后无需重启即可生效
scheduler = BackgroundScheduler()

PORT = int(os.environ.get("ADMIN_PORT", "12345"))
# 口令：环境变量优先，否则取 config.json 的 admin_password；为空=不鉴权
ADMIN_PASSWORD = (os.environ.get("ADMIN_PASSWORD") or getattr(cfg, "ADMIN_PASSWORD", "") or "").strip()


def authorized():
    if not ADMIN_PASSWORD:
        return True
    return request.headers.get("X-Admin-Password") == ADMIN_PASSWORD


def auth_or_401():
    if not authorized():
        return jsonify({"error": "unauthorized"}), 401
    return None


# ---------------------------------------------------------------- 调度
def _day_of_week_expr(weekdays):
    if weekdays == "weekdays":
        return "0-4"          # 周一至周五
    return "0-6"              # 每天（默认）


def setup_scheduler():
    """依据当前 schedule 配置重建调度任务。"""
    scheduler.remove_all_jobs()
    conf = load_config()
    sched = conf.get("schedule", {}) or {}
    if not sched.get("enabled", True):
        app.logger.info("定时推送已关闭，不注册调度任务。")
        return
    hhmm = sched.get("time", "06:30") or "06:30"
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except Exception:
        h, m = 6, 30
    trigger = CronTrigger(hour=h, minute=m, day_of_week=_day_of_week_expr(sched.get("weekdays", "all")))
    scheduler.add_job(main_mod.run_once, trigger=trigger, id="daily_briefing",
                     kwargs={"force": False}, max_instances=1, coalesce=True)
    app.logger.info(f"已注册每日 {hhmm} 定时早报任务（weekdays={sched.get('weekdays','all')}）。")


# ---------------------------------------------------------------- 路由：页面
@app.route("/")
def index():
    return render_template("admin.html", require_auth=bool(ADMIN_PASSWORD))


# ---------------------------------------------------------------- 路由：API
@app.route("/api/meta")
def api_meta():
    return jsonify({"require_auth": bool(ADMIN_PASSWORD), "version": "1.0", "port": PORT})


@app.route("/api/config", methods=["GET"])
def api_get_config():
    deny = auth_or_401()
    if deny:
        return deny
    return jsonify(load_config())


@app.route("/api/config", methods=["PUT"])
def api_put_config():
    deny = auth_or_401()
    if deny:
        return deny
    try:
        conf = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "invalid json"}), 400
    save_config(conf)
    setup_scheduler()  # 时间/星期变化后重建调度
    return jsonify({"ok": True, "config": load_config()})


@app.route("/api/run", methods=["POST"])
def api_run():
    deny = auth_or_401()
    if deny:
        return deny
    data = request.get_json(silent=True) or {}
    force = bool(data.get("force", True))

    def _worker():
        try:
            main_mod.run_once(force=force)
        except Exception as e:
            try:
                from content_generator import log
                log(f"手动执行异常: {e}")
            except Exception:
                pass

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"ok": True, "msg": "已触发，请稍候在日志/状态查看结果。"})


@app.route("/api/test", methods=["POST"])
def api_test():
    deny = auth_or_401()
    if deny:
        return deny
    data = request.get_json(silent=True) or {}
    channel = (data.get("channel") or "").lower()
    test_text = "【测试】每日早报后台连通性测试\n若你收到这条消息，说明该通道配置有效。"
    result = False
    detail = ""
    try:
        if channel == "wxpusher":
            result = ws.send_via_wxpusher(test_text)
        elif channel == "wework":
            mt = getattr(cfg, "WEWORK_MSG_TYPE", "text")
            if mt == "image":
                result = ws._send_wework_image(test_text)
            elif mt == "markdown":
                result = ws._send_wework_markdown(test_text)
            else:
                result = ws._send_wework_text(test_text)
        elif channel == "serverchan":
            for k in getattr(cfg, "SERVERCHAN_KEYS", []) or []:
                if k:
                    result = ws.send_via_serverchan(test_text, k) or result
        elif channel == "dingtalk":
            result = ws.send_via_dingtalk(test_text)
        else:
            detail = "未知通道"
    except Exception as e:
        detail = str(e)
    return jsonify({"ok": bool(result), "channel": channel, "detail": detail})


@app.route("/api/logs", methods=["GET"])
def api_logs():
    deny = auth_or_401()
    if deny:
        return deny
    lines = []
    # 今日运行日志
    log_path = getattr(cfg, "LOG_FILE", "")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-200:]
        except Exception:
            pass
    return jsonify({"log": "".join(lines)})


@app.route("/api/status", methods=["GET"])
def api_status():
    deny = auth_or_401()
    if deny:
        return deny
    # 上次推送
    last_push = ""
    lpf = os.path.join(cfg.PROJECT_DIR, "last_push.txt")
    if os.path.exists(lpf):
        try:
            last_push = open(lpf, "r").read().strip()
        except Exception:
            pass
    # 今日早报预览
    preview = ""
    out_name = f"早报_{datetime.date.today():%Y-%m-%d}.txt"
    out_path = os.path.join(cfg.OUTPUT_DIR, out_name)
    if os.path.exists(out_path):
        try:
            preview = open(out_path, "r", encoding="utf-8").read()[:600]
        except Exception:
            pass
    # 下次运行
    conf = load_config()
    sched = conf.get("schedule", {}) or {}
    next_run = "未启用"
    if sched.get("enabled", True):
        hhmm = sched.get("time", "06:30")
        next_run = f"每日 {hhmm}（北京时间）"
    return jsonify({
        "last_push": last_push or "尚未推送",
        "next_run": next_run,
        "enabled_channels": getattr(cfg, "DELIVERY_CHANNELS", []),
        "preview": preview,
        "source_mode": getattr(cfg, "CONTENT_SOURCE_MODE", ""),
    })


# ---------------------------------------------------------------- 启动
def main():
    apply_overrides()        # 确保启动即应用 config.json
    setup_scheduler()
    if not scheduler.running:
        scheduler.start()
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
