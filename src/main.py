# -*- coding: utf-8 -*-
"""
早报工作台 · 主流程编排
========================================
每日定时执行：解析内容源 -> 生成早报 -> 发送到微信(传输助手/群) -> 兜底备份。

用法：
  python main.py                 # 执行一次（由 Windows 任务计划程序每天定时调用）
  python main.py --url <链接>    # 手动指定文章链接（url 模式 / 调试）
  python main.py --loop          # 常驻内存，按 RUN_HOUR 每天自跑（需电脑不关机）

去重：同一天只推送一次（last_push.txt 记录日期）。
"""
import os
import sys
import datetime

# 让 src 目录可被直接 import
BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import config as cfg
# 在导入其它模块前，先把 config.json 的用户覆盖映射回 config 模块，
# 保证 content_generator / sources / wechat_sender 拿到最新配置。
from config_store import apply_overrides
apply_overrides()
from content_generator import generate, generate_from_html, log
from sources import resolve
from wechat_sender import send_via_wechat, send_via_backup

LAST_PUSH_FILE = os.path.join(cfg.PROJECT_DIR, "last_push.txt")


def already_pushed():
    try:
        if os.path.exists(LAST_PUSH_FILE):
            with open(LAST_PUSH_FILE, "r") as f:
                return f.read().strip() == datetime.date.today().strftime("%Y-%m-%d")
    except Exception:
        pass
    return False


def mark_pushed():
    try:
        with open(LAST_PUSH_FILE, "w") as f:
            f.write(datetime.date.today().strftime("%Y-%m-%d"))
    except Exception:
        pass


def _resolve_with_retry(max_attempts=12, interval=600):
    """当日文章尚未发布时，按 interval 秒间隔重试发现；覆盖约 2 小时窗口。
    365 通常 6–7 点发文，定时任务从 6:30 起每 10 分钟探测一次，
    发文后即刻抓取，避免"太早跑 → 取不到/取错昨天文章"。"""
    import time
    for i in range(max_attempts):
        url, html = resolve()
        if url or html:
            return url, html
        if i < max_attempts - 1:
            log(f"当日文章尚未发布，{interval // 60}分钟后重试（{i + 1}/{max_attempts}）")
            time.sleep(interval)
    return None, None


def run_once(manual_url=None, force=False):
    """执行一次早报生成+发送。供定时调度与手动触发共用。
    - manual_url: 手动指定文章链接（调试/兜底）。
    - force: True 时跳过"今日已推送"去重（手动/测试用）；False 时每日仅推一次。"""
    log("===== 早报任务开始 =====")
    if not force and already_pushed():
        log("今日已推送，跳过。")
        return

    # 重试参数来自后台 schedule 配置（默认 12 次 / 10 分钟，覆盖约 2 小时等待 365 发稿）
    sched = getattr(cfg, "SCHEDULE", {}) or {}
    max_attempts = int(sched.get("max_attempts", 12))
    interval = int(sched.get("interval_minutes", 10)) * 60
    url, html = (manual_url, None) if manual_url else _resolve_with_retry(
        max_attempts=max_attempts, interval=interval)
    if not (url or html):
        log("未获取到当日文章，任务结束。")
        return

    ok, message, err = (generate(url) if url else generate_from_html(html))
    if not ok:
        log(f"生成失败：{err}")
        return

    # 保存生成结果到本地文件，便于人工核对
    out_name = f"早报_{datetime.date.today():%Y-%m-%d}.txt"
    out_path = os.path.join(cfg.OUTPUT_DIR, out_name)
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(message)
        log(f"已保存到: {out_path}")
    except Exception as e:
        log(f"保存文件失败: {e}")

    print("\n" + "=" * 50)
    print(message)
    print("=" * 50 + "\n")

    if not cfg.DELIVERY_ENABLED:
        log("DELIVERY_ENABLED=False：仅生成，未发送任何通道。")
    else:
        sent = send_via_wechat(message)
        if not sent:
            send_via_backup(message)   # 微信不可用时走兜底，确保不漏发
    mark_pushed()
    log("===== 早报任务结束 =====")


def run_daily():
    """每日定时入口：带重试地解析+生成+发送（365 通常 06:35–07:00 发稿，首跑早了靠重试兜底）。"""
    run_once(force=False)


def loop():
    """常驻模式：注入微信 -> 启动监听线程持续捕获 365 推送 -> 每天 RUN_HOUR 生成并发送。
    推荐部署方式（电脑长期开机、微信在线）。"""
    import time
    import threading
    from wechat_sender import init_sdk, watch_and_save, destroy_sdk, _WCF_AVAILABLE

    log("进入常驻模式，每天 %d:00 执行。" % cfg.RUN_HOUR)
    if cfg.WECHAT_ENABLED:
        init_sdk()
    stop = threading.Event()
    watcher = None
    if cfg.WECHAT_ENABLED and _WCF_AVAILABLE:
        watcher = threading.Thread(target=watch_and_save, args=(stop,), daemon=True)
        watcher.start()
    try:
        last_day = None
        while True:
            now = datetime.datetime.now()
            if now.hour == cfg.RUN_HOUR and now.day != last_day:
                last_day = now.day
                try:
                    run_once()
                except Exception as e:
                    log(f"运行异常: {e}")
            time.sleep(30)
    finally:
        stop.set()
        destroy_sdk()


if __name__ == "__main__":
    if "--url" in sys.argv:
        idx = sys.argv.index("--url") + 1
        u = sys.argv[idx] if idx < len(sys.argv) else None
        run_once(manual_url=u, force=True)
    elif "--loop" in sys.argv:
        loop()
    else:
        run_once(force=False)
