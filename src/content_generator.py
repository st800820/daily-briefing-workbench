# -*- coding: utf-8 -*-
"""
早报工作台 · 内容生成核心
========================================
职责：给定《365资讯简报》当日文章 URL，完成
  抓取网页 -> 清洗HTML -> 解析日期/新闻/微语 -> 按规则过滤 -> 重排为最终文本。

本模块与"如何拿到 URL""如何发送"完全解耦，便于复用与测试。
"""
import re
import html
import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config as cfg


def log(msg):
    try:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        log_file = __import__("os").path.join(cfg.LOG_DIR, f"{today}.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now()} - {msg}\n")
    except Exception:
        pass
    print(msg)


def _create_session(retries=3, backoff=0.5, timeout=30):
    s = requests.Session()
    retry = Retry(total=retries, read=retries, connect=retries,
                  backoff_factor=backoff, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "POST"])
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.timeout = timeout
    return s


def fetch_article(url, timeout=20):
    """抓取文章网页 HTML，失败返回 None。"""
    try:
        s = _create_session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.8",
        })
        r = s.get(url, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log(f"抓取失败 {url} -> {e}")
        return None


def clean_html(html_text):
    """去除脚本/标签/冗余文字，保留换行结构。"""
    if not html_text:
        return ""
    text = html.unescape(html_text)
    text = re.sub(r"<(script|style|noscript).*?>.*?</\1>", "", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    garbage = [
        "预览时标签不可点", "向上滑动", "知道了", "微信扫一扫", "赞", "在看",
        "分享", "留言", "收藏", "轻触阅读原文", "365资讯简报 每天一分钟",
        "公众号：365资讯简报", "微信搜", "视频", "小程序", "听过",
    ]
    for kw in garbage:
        text = text.replace(kw, "")
    return text.strip()


def parse_article(text):
    """解析日期行、新闻列表、微语。"""
    date_line = ""
    m = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日\s*星期[一二三四五六日]\s*农历[^\n]+)", text)
    if m:
        date_line = m.group(1).strip()

    micro = ""
    mm = re.search(r"【微语】\s*(.+)", text)
    if mm:
        micro = mm.group(1).strip()
    else:
        mm2 = re.search(r"微语】\s*(.+)", text)
        if mm2:
            micro = mm2.group(1).strip()

    # 仅在「日期行之后、微语之前」的区域内提取编号新闻，
    # 避免误抓页面顶部导航栏里的 "9.9专区" 等干扰项。
    start = text.find(date_line) if date_line else 0
    end = mm.start() if mm else len(text)
    region = text[start:end]
    news_list = []
    for mt in re.finditer(r"^\s*(\d+)\.\s*(.+)", region, re.MULTILINE):
        content = mt.group(2).strip()
        content = re.sub(r"\s+", " ", content)
        if content:
            news_list.append(content)
    return date_line, news_list, micro


def filter_news(news_list):
    """先全采 -> 按规则剔除 -> 保留 NEWS_COUNT 条 -> 重新编号。"""
    kept = []
    for content in news_list:
        if any(w in content for w in cfg.SENSITIVE_WORDS):
            log(f"  剔除(敏感词): {content[:40]}")
            continue
        if any(w in content for w in cfg.EMPLOYEE_WORDS):
            log(f"  剔除(员工词): {content[:40]}")
            continue
        if any(c in content for c in cfg.BANNED_CITIES):
            log(f"  剔除(地市): {content[:40]}")
            continue
        kept.append(content)
        if len(kept) >= cfg.NEWS_COUNT:
            break
    return kept[:cfg.NEWS_COUNT]


def get_weather():
    try:
        r = requests.get("http://apis.juhe.cn/simpleWeather/query",
                         params={"city": cfg.CITY, "key": cfg.WEATHER_KEY}, timeout=10)
        data = r.json()
        if data.get("error_code") == 0:
            info = data["result"]["realtime"]
            weather = info["info"]
            direct = info["direct"]
            power = info["power"]
            temp = str(info.get("temperature", "")).replace("℃", "").replace("°", "").strip()
            emoji_map = {"晴": "☀️", "多云": "⛅", "阴": "☁️", "雨": "🌧️", "雪": "❄️"}
            icon = next((v for k, v in emoji_map.items() if k in weather), "")
            return f"{cfg.CITY}：{weather}{icon}，{direct}{power}，早晨气温：{temp}度"
    except Exception as e:
        log(f"天气获取失败: {e}")
    return f"{cfg.CITY}：天气获取失败"


def get_roses():
    return "🌹" * (datetime.datetime.now().weekday() + 1)


def build_message(date_line, news_list, micro):
    month_day = re.search(r"(\d+月\d+日)", date_line)
    month_day = month_day.group(1) if month_day else ""
    lunar = re.search(r"(农历[^\s]+)", date_line)
    lunar = lunar.group(1) if lunar else ""
    week = re.search(r"(星期[一二三四五六日])", date_line)
    if week:
        weekday = week.group(1)
    else:
        weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][datetime.datetime.now().weekday()]

    header = f"【{cfg.COMPANY_BRAND}】观天下・知今朝！\n{month_day}，{lunar}，{weekday}\n{get_weather()}\n"
    body = "\n".join(f"{i}. {c}" for i, c in enumerate(news_list, 1))
    footer = f"\n【{cfg.COMPANY_BRAND}寄语】{micro.rstrip('。！？').strip()} {get_roses()}"
    return header + body + footer


def generate_from_html(raw_html):
    """HTML 文本 -> (success, message, error)。供 RSS/微信读取等已拿到正文的场景使用。"""
    if not raw_html:
        return False, "", "正文为空"
    clean = clean_html(raw_html)
    date_line, raw_news, micro = parse_article(clean)
    if not raw_news:
        return False, "", "未识别到新闻列表"
    filtered = filter_news(raw_news)
    if not filtered:
        return False, "", "无符合条件的新闻"
    message = build_message(date_line, filtered, micro)
    return True, message, ""


def generate(article_url):
    """主入口：URL -> (success, message, error)。"""
    raw = fetch_article(article_url)
    if not raw:
        return False, "", "抓取文章失败"
    return generate_from_html(raw)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        ok, msg, err = generate(sys.argv[1])
        print(msg if ok else f"失败: {err}")
