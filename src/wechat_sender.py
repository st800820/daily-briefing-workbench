# -*- coding: utf-8 -*-
"""
早报工作台 · 微信适配器（基于 WeChatFerry v39）
========================================
职责：
  1) 注入微信并启动 RPC（sdk.dll -> WxInitSDK），提供 wcf 客户端；
  2) 发送文本到 filehelper / 群（实现"自动发到传输助手 / 直接发群"）；
  3) 捕获《365资讯简报》订阅号当日推送，提取文章链接（v39 无 get_articles，
     只能靠监听推送消息解析 <url>，或人工 --url 兜底）。

⚠️ 重要版本事实（2026-10 实测）：
  - WeChatFerry 只支持微信 3.9.x，不支持 4.x；须安装 3.9.12.51 并锁定版本。
  - v39 的 Python 包名为 wcferry（非老版 wechatferry），客户端类为 Wcf。
  - v39 已移除 get_articles；读文章链接改由"监听捕获推送"实现（见 capture）。

若未安装 wcferry，本模块自动降级为"仅生成不发送"，并打印提示。
"""
import os
import re
import time
import json
import ctypes
import threading

import config as cfg
from content_generator import log

try:
    from wcferry import Wcf, WxMsg
    _WCF_AVAILABLE = True
except Exception:
    _WCF_AVAILABLE = False

_SDK = None          # 已加载的 sdk.dll 句柄
_SDK_INITED = False  # 全局注入状态（一个进程只注入一次）


def init_sdk():
    """加载 release 的 sdk.dll 并向微信注入，启动 RPC(127.0.0.1:10086)。
    需微信已登录且正在运行。幂等：同一进程重复调用安全。返回是否成功。"""
    global _SDK, _SDK_INITED
    if _SDK_INITED:
        return _SDK is not None
    if not _WCF_AVAILABLE:
        log("未安装 wcferry，无法操作微信。")
        return False
    dll = cfg.WECHATFERRY_SDK_DLL
    if not dll or not os.path.exists(dll):
        log("⚠️ 未配置/找不到 sdk.dll（config.WECHATFERRY_SDK_DLL）。无法注入微信，"
            "请按 docs/04 第三节下载 v39.5.2 的 sdk.dll 并填写路径。")
        return False
    try:
        _SDK = ctypes.cdll.LoadLibrary(dll)
        ret = _SDK.WxInitSDK(False, 10086)   # False=不调试；10086=RPC端口
        log(f"WxInitSDK 返回: {ret}（0 表示成功）")
        _SDK_INITED = True
        # 给 RPC 一点起服务的时间
        time.sleep(1.5)
        return True
    except Exception as e:
        log(f"注入微信失败: {e}")
        return False


def destroy_sdk():
    """退出 SDK（释放注入）。进程退出前调用。"""
    global _SDK, _SDK_INITED
    if _SDK:
        try:
            _SDK.WxDestroySDK()
        except Exception:
            pass
    _SDK = None
    _SDK_INITED = False


def get_wcf():
    """获取一个已连接到 RPC 的 Wcf 客户端（自动确保 SDK 已注入）。"""
    if not _WCF_AVAILABLE:
        raise RuntimeError("未安装 wcferry，无法操作微信。请先按部署手册安装。")
    init_sdk()
    return Wcf()


def extract_article_url_from_msg(msg):
    """从一条 WxMsg 中提取《365资讯简报》文章链接。
    命中条件：消息类型为 appmsg(49) 且发送者为 365 订阅号，且正文含 <url>。
    返回 url 字符串或 None。"""
    try:
        mtype = getattr(msg, "type", 0)
        sender = str(getattr(msg, "sender", "") or "")
        content = str(getattr(msg, "content", "") or "")
        if mtype != 49:                       # 49 = 应用消息（订阅号图文推送）
            return None
        if cfg.OFFICIAL_ACCOUNT_WXID not in sender:
            return None
        urls = re.findall(r"<url>\s*(.*?)\s*</url>", content, re.S)
        if urls:
            return urls[0].strip()
    except Exception as e:
        log(f"解析消息提取链接失败: {e}")
    return None


def save_article(url, msg=None, title=""):
    """将捕获到的文章链接写入缓存文件（供每日任务读取）。"""
    try:
        os.makedirs(os.path.dirname(cfg.ARTICLE_CACHE), exist_ok=True)
        data = {
            "url": url,
            "title": title,
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(cfg.ARTICLE_CACHE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log(f"已缓存文章链接: {url}")
    except Exception as e:
        log(f"写入文章缓存失败: {e}")


def load_article():
    """读取文章缓存；若超出有效窗口则返回 None。"""
    try:
        if not os.path.exists(cfg.ARTICLE_CACHE):
            return None
        with open(cfg.ARTICLE_CACHE, "r", encoding="utf-8") as f:
            d = json.load(f)
        url = d.get("url")
        cap = d.get("captured_at", "")
        if not url:
            return None
        try:
            ct = time.mktime(time.strptime(cap, "%Y-%m-%d %H:%M:%S"))
            age_h = (time.time() - ct) / 3600.0
            if age_h > cfg.CAPTURE_MAX_AGE_HOURS:
                log(f"文章缓存已过期（{age_h:.1f}h），需重新捕获")
                return None
        except Exception:
            pass
        return d
    except Exception as e:
        log(f"读取文章缓存失败: {e}")
    return None


def capture_once(wait_seconds=None):
    """一次性捕获：开启接收后轮询若干秒，抓到 365 推送即返回 url。
    注意：仅能抓到"开启接收之后"实时到达的推送；若当日推送已早于本调用到达，
    队列中可能已无该消息，故本函数仅作兜底。可靠方案是常驻监听（见 main --loop）。"""
    if not _WCF_AVAILABLE:
        return None
    wait_seconds = wait_seconds or cfg.CAPTURE_WAIT_SECONDS
    try:
        wcf = get_wcf()
        wcf.enable_receiving_msg()
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            try:
                msg = wcf.get_msg(block=False)
            except Exception:
                msg = None
            if msg is not None:
                u = extract_article_url_from_msg(msg)
                if u:
                    save_article(u)
                    return u
            time.sleep(1)
    except Exception as e:
        log(f"一次性捕获失败: {e}")
    return None


def watch_and_save(stop_event):
    """常驻监听线程：持续接收消息，捕获 365 推送并写入缓存。
    由 main --loop 启动；需微信已注入并登录。"""
    if not _WCF_AVAILABLE:
        log("wcferry 不可用，监听线程退出。")
        return
    try:
        wcf = get_wcf()
        wcf.enable_receiving_msg()
        log("文章监听已启动，等待《365资讯简报》推送…")
        while not stop_event.is_set():
            try:
                msg = wcf.get_msg(block=False)
            except Exception:
                msg = None
            if msg is not None:
                u = extract_article_url_from_msg(msg)
                if u:
                    save_article(u)
            time.sleep(1)
    except Exception as e:
        log(f"监听线程异常: {e}")


class WeChatSender:
    def __init__(self):
        self.wcf = get_wcf()

    def send_text(self, target, text):
        """发送文本到指定 wxid（filehelper=传输助手；xxx@chatroom=群）。
        返回 0 表示成功。"""
        try:
            ret = self.wcf.send_text(text, target)
            if ret == 0:
                log(f"微信发送成功 -> {target}")
                return True
            log(f"微信发送返回非零: {ret}")
            return False
        except Exception as e:
            log(f"微信发送失败: {e}")
            return False


def send_via_wechat(text, target=None):
    """对外统一入口：发送文本到配置目标。失败返回 False。"""
    if not cfg.WECHAT_ENABLED:
        log("微信发送已禁用（config.WECHAT_ENABLED=False）")
        return False
    if not _WCF_AVAILABLE:
        log("⚠️ 未安装 wcferry：跳过微信发送，仅生成内容。")
        return False
    try:
        wcs = WeChatSender()
        return wcs.send_text(target or cfg.WECHAT_TARGET, text)
    except Exception as e:
        log(f"微信发送异常: {e}")
        return False


def _is_emoji_base(ch):
    o = ord(ch)
    return (0x1F000 <= o <= 0x1FAFF) or (0x2600 <= o <= 0x27BF) or (0x2B00 <= o <= 0x2BFF)


def _iter_tokens(line):
    """把一行拆成 (片段, 是否emoji) 列表；emoji 片段连同其变体选择符/ZWJ 组合一起返回。"""
    tokens, i, n = [], 0, len(line)
    while i < n:
        if _is_emoji_base(line[i]):
            j = i + 1
            while j < n and (ord(line[j]) in (0xFE0F, 0xFE0E, 0x200D)
                             or 0x1F3FB <= ord(line[j]) <= 0x1F3FF):
                j += 1
            tokens.append((line[i:j], True))
            i = j
        else:
            j = i
            while j < n and not _is_emoji_base(line[j]):
                j += 1
            tokens.append((line[i:j], False))
            i = j
    return tokens


def render_briefing_image(text, out_path=None):
    """把早报文本渲染成一张 PNG 卡片（格式 100% 保留，不受任何通道渲染影响）。
    中文用系统黑体/雅黑，emoji 用 Segoe UI Emoji（彩色），找不到字体则回退默认。
    返回图片路径。"""
    from PIL import Image, ImageDraw, ImageFont
    out_path = out_path or os.path.join(cfg.OUTPUT_DIR, f"早报_{time.strftime('%Y-%m-%d')}.png")
    cjk = next((f for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                            "C:/Windows/Fonts/simsun.ttc") if os.path.exists(f)), None)
    emo = next((f for f in ("C:/Windows/Fonts/seguiemj.ttf",
                            "C:/Windows/Fonts/segoeuiemoji.ttf") if os.path.exists(f)), None)
    title_size, body_size = 32, 26
    t_cjk = ImageFont.truetype(cjk, title_size) if cjk else ImageFont.load_default()
    b_cjk = ImageFont.truetype(cjk, body_size) if cjk else ImageFont.load_default()
    t_emo = ImageFont.truetype(emo, title_size) if emo else None
    b_emo = ImageFont.truetype(emo, body_size) if emo else None

    max_px = 640  # 内容区最大像素宽
    rendered = []  # [(tokens, is_title)]
    for i, line in enumerate(text.split("\n")):
        is_title = (i == 0)
        cjk_f = t_cjk if is_title else b_cjk
        emo_f = t_emo if is_title else b_emo
        cur, cur_w = [], 0.0
        for tok, is_emoji in _iter_tokens(line):
            f = emo_f if (is_emoji and emo_f) else cjk_f
            w = f.getlength(tok)
            if cur and cur_w + w > max_px:
                rendered.append((cur, is_title))
                cur, cur_w = [], 0.0
            cur.append((tok, is_emoji))
            cur_w += w
        rendered.append((cur, is_title))

    pad = 36
    lh_title, lh_body = int(title_size * 1.7), int(body_size * 1.7)
    def line_w(tokens, is_title):
        cjk_f = t_cjk if is_title else b_cjk
        emo_f = t_emo if is_title else b_emo
        return sum((emo_f if (e and emo_f) else cjk_f).getlength(t) for t, e in tokens)
    content_w = int(max(line_w(tk, t) for tk, t in rendered)) if rendered else 0
    w = content_w + pad * 2
    h = pad * 2 + sum(lh_title if t else lh_body for _, t in rendered)

    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    brand = (31, 78, 121)
    y = pad
    for tokens, is_title in rendered:
        cjk_f = t_cjk if is_title else b_cjk
        emo_f = t_emo if is_title else b_emo
        x = pad
        fill = brand if is_title else (20, 20, 20)
        for tok, is_emoji in tokens:
            if is_emoji and emo_f:
                try:
                    draw.text((x, y), tok, font=emo_f, embedded_color=True)
                except TypeError:
                    draw.text((x, y), tok, font=emo_f, fill=fill)
                x += emo_f.getlength(tok)
            else:
                draw.text((x, y), tok, font=cjk_f, fill=fill)
                x += cjk_f.getlength(tok)
        y += lh_title if is_title else lh_body
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "PNG")
    log(f"已渲染早报图片: {out_path}")
    return out_path


def _send_wework_text(text):
    import requests
    r = requests.post(cfg.WEWORK_WEBHOOK, json={"msgtype": "text", "text": {"content": text}}, timeout=15)
    return r.json().get("errcode") == 0


def _send_wework_image(text):
    import hashlib
    import base64
    import requests
    path = render_briefing_image(text)
    with open(path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("ascii")
    md5 = hashlib.md5(data).hexdigest()
    r = requests.post(cfg.WEWORK_WEBHOOK,
                     json={"msgtype": "image", "image": {"base64": b64, "md5": md5}}, timeout=20)
    return r.json().get("errcode") == 0


def _to_markdown(text):
    out = []
    for line in text.split("\n"):
        if line.startswith("【") and "】" in line[:20]:
            out.append(f"**{line}**")
        elif re.match(r"^\d+\.\s", line):
            out.append(f"> {line}")
        else:
            out.append(line)
    return "\n".join(out)


def _send_wework_markdown(text):
    import requests
    r = requests.post(cfg.WEWORK_WEBHOOK,
                     json={"msgtype": "markdown", "markdown": {"content": _to_markdown(text)}}, timeout=15)
    return r.json().get("errcode") == 0


def send_via_wxpusher(text):
    """通过 WxPusher 把消息推到个人微信（公众号会话，非服务通知，格式不乱）。
    按 token 前缀自动区分两种模式：
      - SPT_ 开头（极简推送）：POST /api/send/message/simple-push，传 spt 字段，无需 UID（绑定扫码的微信）。
      - AT_  开头（标准推送）：POST /api/send/message，传 appToken + uids(UID_)。
    返回是否成功。"""
    token = getattr(cfg, "WX_PUSHER_TOKEN", "")
    if not token:
        log("未配置 WX_PUSHER_TOKEN，跳过 WxPusher 推送")
        return False
    import requests
    if token.startswith("SPT_"):
        # 极简推送：token 即 SPT，无需 UID
        url = "https://wxpusher.zjiecode.com/api/send/message/simple-push"
        payload = {
            "content": text,
            "contentType": 1,            # 1=文本（保留换行）
            "summary": "每日早报",
            "spt": token,
        }
    else:
        # 标准推送：appToken(AT_) + uids(UID_)
        url = "https://wxpusher.zjiecode.com/api/send/message"
        payload = {
            "appToken": token,
            "content": text,
            "contentType": 1,
            "summary": "每日早报",
            "uids": getattr(cfg, "WX_PUSHER_UIDS", []) or [],
        }
    try:
        r = requests.post(url, json=payload, timeout=15)
        data = r.json()
        if data.get("success"):
            # 标准模式 data 为列表，逐条核验是否真正送达（顶层 success 只代表请求被接收，
            # 接收人未关注应用时顶层仍 success，但条目 code=1001、status 写明"未订阅"）。
            items = data.get("data")
            if isinstance(items, list):
                failed = [it for it in items if it.get("code") != 1000]
                if failed:
                    for it in failed:
                        log(f"WxPusher 送达失败: {it.get('status') or it.get('msg')}")
                    log("提示：若提示'未订阅应用'，请到 wxpusher.com/admin 复制该应用的"
                        "「关注链接/二维码」，用微信扫码关注应用后再推送。")
                    return False
            log("WxPusher 推送成功（直达个人微信）")
            return True
        log(f"WxPusher 推送返回未成功: {data}")
    except Exception as e:
        log(f"WxPusher 推送失败: {e}")
    return False


def send_via_backup(text):
    """兜底推送：按 config.DELIVERY_CHANNELS 依次尝试。
    通道说明：
      - wxpusher  ：WxPusher 极简推送，直达个人微信（公众号会话），格式稳定，免注册。
      - wework    ：企业微信机器人（text/image/markdown，由 WEWORK_MSG_TYPE 选），格式稳定。
      - serverchan：Server酱推到「微信服务通知」，渲染差、易串行，默认不启用。
      - dingtalk  ：钉钉自定义机器人（text），加签可选，落钉钉群。
      - wechat    ：WeChatFerry 发文件传输助手/群（需降级微信，当前不可用）。
    """
    channels = [c.lower() for c in getattr(cfg, "DELIVERY_CHANNELS", ["wxpusher", "wework"])]
    ok = False
    if "wxpusher" in channels:
        ok = send_via_wxpusher(text) or ok
    if "wework" in channels and cfg.WEWORK_WEBHOOK:
        mtype = getattr(cfg, "WEWORK_MSG_TYPE", "text")
        try:
            if mtype == "image":
                ok = _send_wework_image(text) or ok
            elif mtype == "markdown":
                ok = _send_wework_markdown(text) or ok
            else:
                ok = _send_wework_text(text) or ok
            if ok:
                log(f"企业微信机器人推送成功（msgtype={mtype}）")
        except Exception as e:
            log(f"企业微信推送失败: {e}")
    if "serverchan" in channels:
        for key in cfg.SERVERCHAN_KEYS:
            if not key:
                continue
            if send_via_serverchan(text, key):
                ok = True
    if "dingtalk" in channels and getattr(cfg, "DINGTALK_WEBHOOK", ""):
        ok = send_via_dingtalk(text) or ok
    return ok


def send_via_serverchan(text, key=None):
    """Server酱：推到微信「服务通知」。key 为 SCT... 形式的 SendKey。"""
    import requests
    key = key or (getattr(cfg, "SERVERCHAN_KEYS", []) or [None])[0]
    if not key:
        log("Server酱：未配置 SendKey，跳过。")
        return False
    try:
        r = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                         data={"title": "每日早报", "desp": text}, timeout=15)
        if r.json().get("code") == 0:
            log("Server酱推送成功（兜底）")
            return True
        log(f"Server酱返回: {r.text[:200]}")
    except Exception as e:
        log(f"Server酱推送失败: {e}")
    return False


def send_via_dingtalk(text, webhook=None, secret=None):
    """钉钉自定义机器人（text 消息）。
    webhook 形如 https://oapi.dingtalk.com/robot/send?access_token=xxx
    若配置了加签 secret：按官方规则用 timestamp+secret 做 HMAC-SHA256，
    结果 base64 后 URL 编码，作为 sign 参数追加到 webhook。"""
    import requests
    import base64
    import hashlib
    import hmac
    import urllib.parse

    url = (webhook or getattr(cfg, "DINGTALK_WEBHOOK", "")).strip()
    secret = (secret if secret is not None else getattr(cfg, "DINGTALK_SECRET", "")) or ""
    if not url:
        log("钉钉推送：未配置 webhook，跳过。")
        return False
    try:
        if secret:
            timestamp = str(int(time.time() * 1000))
            string_to_sign = f"{timestamp}\n{secret}"
            hmac_code = hmac.new(secret.encode("utf-8"),
                                 string_to_sign.encode("utf-8"),
                                 hashlib.sha256).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}timestamp={timestamp}&sign={sign}"
        payload = {"msgtype": "text", "text": {"content": text}}
        r = requests.post(url, json=payload, timeout=15)
        data = r.json()
        if data.get("errcode") == 0:
            log("钉钉机器人推送成功（落钉钉群）")
            return True
        log(f"钉钉推送返回错误: {data}")
    except Exception as e:
        log(f"钉钉推送失败: {e}")
    return False
