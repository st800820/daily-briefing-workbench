# -*- coding: utf-8 -*-
"""
早报工作台 · 配置热更新层
========================================
把"写死在 config.py 的默认值"与"用户通过网页后台改的 config.json"合并，并实时映射回
config 模块的属性，供 content_generator / sources / wechat_sender / main 直接读取。

设计要点：
  - config.py 仍是唯一默认值来源（换电脑只改它也能跑）。
  - config.json 是网页后台写出的"用户覆盖层"，不纳入版本管理（已在 .gitignore 精神内）。
  - apply_overrides() 必须在 import 其它模块（content_generator/sources/wechat_sender）之前调用，
    这样模块顶层若拷贝了 cfg 属性也能拿到最新值。
"""
import os
import json
import copy

import config as cfg


CONFIG_JSON = os.path.join(cfg.PROJECT_DIR, "config.json")

# 通道固定优先级（决定 DELIVERY_CHANNELS 的顺序）
_CHANNEL_ORDER = ["wxpusher", "wework", "serverchan", "dingtalk", "wechat"]


def default_config():
    """返回一份完整默认配置（深拷贝，避免后续修改污染 config 模块）。"""
    return {
        "brand": cfg.COMPANY_BRAND,
        "news_count": cfg.NEWS_COUNT,
        "city": cfg.CITY,
        "weather_key": cfg.WEATHER_KEY,
        "tz": "Asia/Shanghai",
        "source_mode": cfg.CONTENT_SOURCE_MODE,
        "netease_home": cfg.NETEASE_HOME,
        "schedule": {
            "enabled": True,
            "time": "06:30",
            "max_attempts": 12,
            "interval_minutes": 10,
            "weekdays": "all",   # all / weekdays / 自定义
        },
        "channels": {
            "wxpusher": {
                "enabled": bool(getattr(cfg, "WX_PUSHER_TOKEN", "")),
                "token": getattr(cfg, "WX_PUSHER_TOKEN", ""),
                "uids": getattr(cfg, "WX_PUSHER_UIDS", []) or [],
                "sub_channel": "clawbot",   # clawbot(落微信) / app(落客户端) —— 仅作提示，API 相同
            },
            "wework": {
                "enabled": bool(getattr(cfg, "WEWORK_WEBHOOK", "")),
                "webhook": getattr(cfg, "WEWORK_WEBHOOK", ""),
                "msg_type": getattr(cfg, "WEWORK_MSG_TYPE", "text"),
            },
            "serverchan": {
                "enabled": False,
                "keys": getattr(cfg, "SERVERCHAN_KEYS", []) or [],
            },
            "dingtalk": {
                "enabled": False,
                "webhook": getattr(cfg, "DINGTALK_WEBHOOK", ""),
                "secret": getattr(cfg, "DINGTALK_SECRET", ""),
            },
            "wechat": {
                "enabled": bool(getattr(cfg, "WECHAT_ENABLED", False)),
                "target": getattr(cfg, "WECHAT_TARGET", "filehelper"),
            },
        },
        "filters": {
            "banned_cities": list(getattr(cfg, "BANNED_CITIES", []) or []),
            "sensitive_words": list(getattr(cfg, "SENSITIVE_WORDS", []) or []),
            "employee_words": list(getattr(cfg, "EMPLOYEE_WORDS", []) or []),
        },
        "failure_alert": True,
        "admin_password": "",
    }


def _deep_merge(base, override):
    """把 override 的非空键递归合进 base（仅合并已知结构，避免脏数据覆盖）。"""
    if not isinstance(override, dict):
        return base
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config():
    """返回合并后的完整配置字典（默认 + config.json）。"""
    conf = default_config()
    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            conf = _deep_merge(conf, data)
        except Exception as e:
            # 配置损坏不应让整个程序崩溃，退回默认并记下
            try:
                from content_generator import log
                log(f"读取 config.json 失败，使用默认配置: {e}")
            except Exception:
                pass
    return conf


def _apply_channels(channels):
    c = channels or {}
    wx = c.get("wxpusher", {}) or {}
    cfg.WX_PUSHER_TOKEN = wx.get("token", "") or ""
    cfg.WX_PUSHER_UIDS = wx.get("uids", []) or []
    cfg.WX_PUSHER_SUBCHANNEL = wx.get("sub_channel", "clawbot")

    we = c.get("wework", {}) or {}
    cfg.WEWORK_WEBHOOK = we.get("webhook", "") or ""
    cfg.WEWORK_MSG_TYPE = we.get("msg_type", "text")

    sc = c.get("serverchan", {}) or {}
    cfg.SERVERCHAN_KEYS = sc.get("keys", []) or []

    dt = c.get("dingtalk", {}) or {}
    cfg.DINGTALK_WEBHOOK = dt.get("webhook", "") or ""
    cfg.DINGTALK_SECRET = dt.get("secret", "") or ""

    wc = c.get("wechat", {}) or {}
    cfg.WECHAT_ENABLED = bool(wc.get("enabled", False))
    cfg.WECHAT_TARGET = wc.get("target", "filehelper")

    enabled = [ch for ch in _CHANNEL_ORDER if (c.get(ch, {}) or {}).get("enabled")]
    cfg.DELIVERY_CHANNELS = enabled
    cfg.DELIVERY_ENABLED = bool(enabled)


def apply_overrides():
    """读 config.json 并映射回 config 模块属性。import 其它模块前调用一次即可。"""
    conf = load_config()

    cfg.COMPANY_BRAND = conf.get("brand", cfg.COMPANY_BRAND)
    cfg.NEWS_COUNT = int(conf.get("news_count", cfg.NEWS_COUNT))
    cfg.CITY = conf.get("city", cfg.CITY)
    cfg.WEATHER_KEY = conf.get("weather_key", cfg.WEATHER_KEY)
    cfg.CONTENT_SOURCE_MODE = conf.get("source_mode", cfg.CONTENT_SOURCE_MODE)
    cfg.NETEASE_HOME = conf.get("netease_home", cfg.NETEASE_HOME)

    sched = conf.get("schedule", {}) or {}
    hhmm = sched.get("time", "06:30") or "06:30"
    try:
        cfg.RUN_HOUR = int(hhmm.split(":")[0])
    except Exception:
        cfg.RUN_HOUR = 7
    cfg.SCHEDULE = sched

    flt = conf.get("filters", {}) or {}
    cfg.BANNED_CITIES = flt.get("banned_cities", cfg.BANNED_CITIES) or []
    cfg.SENSITIVE_WORDS = flt.get("sensitive_words", cfg.SENSITIVE_WORDS) or []
    cfg.EMPLOYEE_WORDS = flt.get("employee_words", cfg.EMPLOYEE_WORDS) or []

    cfg.FAILURE_ALERT = bool(conf.get("failure_alert", True))
    cfg.ADMIN_PASSWORD = conf.get("admin_password", "") or ""

    _apply_channels(conf.get("channels", {}))

    # 同步到 sources 模块（其顶层拷贝了 NETEASE_HOME）
    try:
        import sources
        sources.NETEASE_HOME = cfg.NETEASE_HOME
    except Exception:
        pass
    return conf


def save_config(conf):
    """校验并写出 config.json，随后立即 apply_overrides 让本次改动即时生效。"""
    conf = copy.deepcopy(conf)
    # 基础校验，避免明显坏值
    if "news_count" in conf:
        conf["news_count"] = max(1, min(20, int(conf["news_count"])))
    if "schedule" in conf and "time" in conf["schedule"]:
        # 简单 HH:MM 校验
        parts = str(conf["schedule"]["time"]).split(":")
        if len(parts) != 2 or not (0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59):
            conf["schedule"]["time"] = "06:30"
    with open(CONFIG_JSON, "w", encoding="utf-8") as f:
        json.dump(conf, f, ensure_ascii=False, indent=2)
    apply_overrides()
    return conf
