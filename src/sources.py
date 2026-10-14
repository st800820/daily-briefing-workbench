# -*- coding: utf-8 -*-
"""
早报工作台 · 内容源适配器
========================================
负责"拿到《365资讯简报》当日文章"，返回可直接生成内容的：
  - URL（HTML 页），或
  - 原始 HTML 文本（RSS/Atom 或 微信读取）。

模式（见 config.CONTENT_SOURCE_MODE）：
  netease：转载《365资讯简报》的网易号固定主页，静态可抓、无验证码、无歧义（当前主用·已验证）
  wechat ：通过微信客户端捕获订阅号当日推送（需降级到微信3.9+WeChatFerry，暂不可用）
  search ：通过 Anspire 搜索API发现当天文章URL（实测命中率低，仅兜底）
  rss    ：从配置的镜像/RSS 源自动抓取（源多已失效）
  url    ：手动传入链接（兜底）

【netease 模式为什么能成立】
  《365资讯简报》每天被网易号稳定转载，其固定主页 m.163.com/news/sub/T1603594732083.html
  是静态页面（普通 requests 即可抓取，不需要浏览器/JS/验证码），按时间列出每天文章链接。
  脚本抓主页 -> 取最新若干文章链接 -> 逐个核验其正文日期是否为"今天" -> 命中即返回。
  完全不依赖微信、不依赖降级、不依赖搜索，且适配"电脑锁屏"场景（纯 HTTP）。
"""
import re
import datetime
import requests
from xml.etree import ElementTree

import config as cfg
from content_generator import log


def _today_md():
    now = datetime.datetime.now()
    return f"{now.month}月{now.day}日"


# —— 网易号固定主页（转载《365资讯简报》，配置见 config.NETEASE_HOME）——
# 注意：NETEASE_HOME 改为惰性读取 cfg.NETEASE_HOME（见 get_from_netease），
# 以便网页后台改配置后能即时生效（不再在模块顶层拷贝固定值）。
NETEASE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")


def _article_is_today(date_line, today):
    """核验文章自身的发布日期是否为 today。

    不能用"正文里出现 X月X日"这种松散判断——昨天文章里常提到"明日X月X日"，
    会在 365 尚未发文时把昨天的文章误判为今天。必须以文章自带 date_line 为准。"""
    if not date_line:
        return False
    m = re.search(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日", date_line)
    if not m:
        return False
    mo, d = int(m.group(2)), int(m.group(3))
    if m.group(1):  # 含年份 -> 严格比对年/月/日
        return int(m.group(1)) == today.year and mo == today.month and d == today.day
    return mo == today.month and d == today.day


def get_from_netease(target_date=None):
    """
    通过网易号固定主页发现当天《365资讯简报》文章。
    返回 (url, None) 或 (None, None)。
    ⚠️ 严格按文章自身的发布日期(date_line)比对今天，避免把"明日X月X日"误判为今日
       （否则在 365 尚未发文时，会把昨天的文章当今天推送出去，已踩过坑：2026-10-14 早）。
    """
    today = target_date or datetime.date.today()
    try:
        home = cfg.NETEASE_HOME   # 惰性读取，支持网页后台热更新
        r = requests.get(home, headers={"User-Agent": NETEASE_UA,
                                        "Accept-Language": "zh-CN,zh;q=0.9"}, timeout=25)
        r.raise_for_status()
        links = re.findall(r'https?://www\.163\.com/dy/article/[A-Za-z0-9]+\.html', r.text)
        seen, uniq = set(), []
        for u in links:
            if u not in seen:
                seen.add(u)
                uniq.append(u)
        if not uniq:
            log("网易号主页未提取到文章链接")
            return None, None
        # 取最新若干篇，逐篇核验"文章自身发布日期"是否为今天（避免取错/节假日跳更）
        from content_generator import fetch_article, clean_html, parse_article
        for url in uniq[:8]:
            try:
                raw = fetch_article(url)
                if not raw:
                    continue
                date_line, _, _ = parse_article(clean_html(raw))
                if _article_is_today(date_line, today):
                    log(f"网易号命中今日文章: {url}（{date_line}）")
                    return url, None
            except Exception:
                continue
        log(f"网易号前8篇均非今日({today})文章（可能365当日尚未发布或跳更）")
    except Exception as e:
        log(f"网易号主页获取失败: {e}")
    return None, None


def get_from_mirror(mirror_url):
    """HTML 镜像页（如 m.365jianbao.com/daily）直接返回 URL 即可。"""
    return mirror_url, None


def get_from_rss(rss_url):
    """Atom/RSS 源：找到今日条目，返回其正文 HTML。"""
    try:
        r = requests.get(rss_url, timeout=20)
        r.raise_for_status()
        root = ElementTree.fromstring(r.content)
        today = _today_md()
        # Atom
        for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
            title = entry.findtext("{http://www.w3.org/2005/Atom}title") or ""
            if today in title:
                c = entry.findtext("{http://www.w3.org/2005/Atom}content")
                s = entry.findtext("{http://www.w3.org/2005/Atom}summary")
                return None, (c or s)
        # RSS
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            if today in title:
                c = item.findtext("description")
                ce = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
                return None, (ce or c)
        log("RSS 未找到今日文章")
        return None, None
    except Exception as e:
        log(f"RSS 获取失败: {e}")
        return None, None


def get_from_wechat():
    """
    通过微信客户端获取《365资讯简报》当日文章链接。
    ⚠️ 需要把微信降级到 3.9.x 并安装 WeChatFerry 才能工作（用户当前为微信4.x，暂不可用）。
    返回：(article_url, html_or_None)
    """
    try:
        from wechat_sender import load_article
        cached = load_article()
        if cached and cached.get("url"):
            log(f"微信读取（缓存）：{cached['url']}")
            return cached["url"], None
    except Exception as e:
        log(f"读微信缓存失败: {e}")
    log("微信读取：需降级微信+WeChatFerry，当前不可用")
    return None, None


def get_from_search(target_date=None):
    """
    通过 Anspire 搜索API发现当天《365资讯简报》文章URL。
    ⚠️ 实测（2026-10-13）该搜索对"365资讯简报+日期"返回无关新闻页，命中率低，仅作兜底。
    """
    today = target_date or datetime.date.today()
    q = f"365资讯简报 {today.year}年{today.month}月{today.day}日"
    try:
        r = requests.get(
            cfg.ANSPIRE_SEARCH_URL,
            params={"query": q, "top_k": 10},
            headers={"Authorization": f"Bearer {cfg.ANSPIRE_API_KEY}", "Accept": "application/json"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        for item in data.get("results", []):
            u = item.get("url", "") or ""
            title = item.get("title", "") or ""
            content = item.get("content", "") or ""
            is_repost = any(d in u for d in ("163.com", "mp.weixin.qq.com", "toutiao.com"))
            is_365 = ("365资讯简报" in (title + content)) or f"{today.year}年{today.month}月{today.day}日" in content
            if is_repost and is_365:
                log(f"搜索命中365文章: {u}")
                return u, None
        log("搜索未发现可靠的365文章（命中率低，符合预期）")
    except Exception as e:
        log(f"搜索发现失败: {e}")
    return None, None


def resolve(target_date=None):
    """
    根据 config.CONTENT_SOURCE_MODE 解析当日文章。
    返回 (url, html) 其中至少有一个非空。
    """
    mode = cfg.CONTENT_SOURCE_MODE
    if mode == "url":
        raise ValueError("url 模式需在 main 中手动传入链接")
    if mode == "netease":
        return get_from_netease(target_date)
    if mode == "wechat":
        return get_from_wechat()
    if mode == "search":
        return get_from_search(target_date)
    # 默认：依次尝试其他源作为兜底
    for src in cfg.RSS_MIRRORS:
        if src.endswith((".atom", ".rss", "/feeds/")) or "rss" in src or "feed" in src:
            url, html = get_from_rss(src)
        else:
            url, html = get_from_mirror(src)
        if url or html:
            return url, html
    return None, None
