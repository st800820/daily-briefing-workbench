# -*- coding: utf-8 -*-
"""
早报工作台 · 统一配置文件（开源版 / 已脱敏）
========================================
本文件集中管理所有可配置项，便于在不同电脑 / 不同账号之间复用。

⚠️⚠️⚠️ 安全提示（开源版）
  - 本文件所有密钥/Token/Webhook 均已清空为占位符，**不含任何真实隐私信息**。
  - 真实配置请放在项目根目录的 config.json（由网页后台生成，已纳入 .gitignore，切勿提交）。
  - 也可在本文件把带【需填写】标记的项改成你自己的值；或新建 config_local.py 覆盖（同样不入库）。
  - 切勿把真实 config.json、config_local.py、*.log、output/ 提交到公开仓库！

复用方法：
  1. 把整个项目文件夹拷贝到目标环境；
  2. 安装依赖：pip install -r requirements.txt；
  3. 复制 config.example.json 为 config.json，填入你自己的密钥（或启动网页后台填写）；
  4. 按 docs/渠道配置.md 完成各推送渠道与定时任务配置。

注意：本仓库为通用开源版本，已移除原作者私有配置。
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
LOG_DIR = os.path.join(PROJECT_DIR, "logs")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")   # 生成结果保存目录（便于人工核对）
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ===================== 基础信息 =====================
COMPANY_BRAND = "你的品牌名"          # 【可按需修改】报头品牌名
CITY = "你的城市"                     # 【需填写】天气城市名（如：北京、上海；聚合数据免费接口仅支持地级市）
WEATHER_KEY = ""                      # 【需填写】聚合数据 天气API key（免费申请：https://www.juhe.cn/docs/api/id/73）

# ===================== 公众号内容源 =====================
# 《365资讯简报》公众号：微信号 infor365，原始ID gh_9a06dc237662。发文时段约 6:00–7:00。
# 下方 BIZ 为该公众号的 fakeid（公开标识，非隐私），仅供参考。
OFFICIAL_ACCOUNT_NAME = "365资讯简报"
OFFICIAL_ACCOUNT_BIZ = "MzI4Njc4ODE1NA=="

# 转载《365资讯简报》的网易号固定主页（公开、稳定可用）。
# 该页为静态HTML（普通 requests 即可抓取，无需浏览器/JS/验证码），
# 按时间列出每天文章链接，脚本抓主页->取最新若干->核验正文日期->命中今日即返回。
# 这是"不碰微信、不降级、锁屏也能跑"的可靠自动发现源。
NETEASE_HOME = "https://m.163.com/news/sub/T1603594732083.html"

# 备用稳定镜像 / RSS 源（多数已失效，仅保留位）
RSS_MIRRORS = [
    # "https://m.365jianbao.com/daily",  # 已失效，勿启用
]

# ===================== 搜索 API（Anspire，兜底用）=====================
# 实测结论：Anspire ntsearch 对"365资讯简报+日期"查询返回无关新闻页，
# 不能稳定命中365原文/转载，故 search 模式仅作兜底。Key 留空，需要时自行申请。
ANSPIRE_API_KEY = ""                # 【可选】Anspire 开放平台 API Key
ANSPIRE_SEARCH_URL = "https://plugin.anspire.cn/api/ntsearch/search"

# 内容源模式：netease(网易号主页·已验证·推荐) / wechat(读微信客户端·需降级到3.9) /
#              search(Anspire搜索·实测不稳定) / rss(镜像源·已失效) / url(手动传入)
CONTENT_SOURCE_MODE = "netease"

# ===================== 微信发送（WeChatFerry v39，需降级微信，默认关）=====================
# ⚠️ WeChatFerry 只支持微信 3.9.x，不支持 4.x。
#    当前主流微信为 4.x，启用此通道必须降级到 3.9.12.51，风险自担，默认关闭。
WECHAT_ENABLED = False             # 默认关闭（需降级微信）

# WeChatFerry release（v39.5.2）的 sdk.dll 路径（降级后填绝对路径启用）。
WECHATFERRY_SDK_DLL = r""

# 《365资讯简报》订阅号 wxid（原始ID gh_9a06dc237662）。
OFFICIAL_ACCOUNT_WXID = "gh_9a06dc237662"

# 捕获到的当日文章链接缓存（降级方案用）。
ARTICLE_CACHE = os.path.join(PROJECT_DIR, "data", "last_article.json")
CAPTURE_MAX_AGE_HOURS = 20
CAPTURE_WAIT_SECONDS = 120

# 发送目标（降级方案启用时）：
#   第一阶段 = "filehelper"  （文件传输助手，人工核对后转发群）
#   第二阶段 = "xxxx@chatroom"（指定群聊 wxid，直接发群）
WECHAT_TARGET = "filehelper"
WECHAT_TARGET_PHASE2 = ""          # 第二阶段填写目标群 wxid

# ===================== 内容过滤规则 =====================
NEWS_COUNT = 10                    # 最终保留新闻条数
BANNED_CITIES = [
    "黑龙江", "贵州", "太原", "江西", "江苏", "浙江", "安徽",
    "广东", "河南", "河北", "湖南", "湖北", "陕西", "甘肃", "青海", "海南",
    "云南", "福建", "广西", "内蒙古", "新疆", "西藏", "宁夏", "辽宁", "吉林",
]
SENSITIVE_WORDS = ["绑架", "强奸", "自杀"]
EMPLOYEE_WORDS = [
    "工资", "社保", "待遇", "工会", "离职", "补偿", "裁员", "欠薪", "加班", "福利",
    "公积金", "劳动合同", "劳动争议", "招聘", "求职", "就业",
]

# ===================== 兜底推送渠道（可选）=====================
# 企业微信机器人 Webhook（无人值守时的备份/告警通道，格式稳定）
WEWORK_WEBHOOK = ""                # 【需填写】企业微信机器人 Webhook 完整 URL
# 企业微信消息类型：text(原样多行·推荐) / image(渲染图片·最稳) / markdown(轻美化)
WEWORK_MSG_TYPE = "text"

# ===================== WxPusher 推送（直达个人微信·免注册·保格式）=====================
# 无需注册企业微信：微信扫码关注 WxPusher 公众号 -> 在「我的」里生成 SPT 极简推送 token（免注册/免建应用）；
# 或注册 wxpusher 账号创建应用拿 appToken(AT_...) + 接收者 UID。
# 通过 WxPusher 自己的公众号把消息发到你的个人微信（公众号会话，非服务通知），支持文本/HTML/Markdown，格式不乱。
# 极简推送 SPT（推荐，免注册）：只填 WX_PUSHER_TOKEN="SPT_xxx" 即可，uids 留空（自动发给自己）。
#   取 SPT：微信扫码打开 WxPusher -> 我的 -> 极简推送 -> 复制 SPT_ 开头 token（切勿泄露）。
# 标准推送（AT_）：还需填 WX_PUSHER_UIDS（关注应用后的 UID_xxx）。
WX_PUSHER_TOKEN = ""               # 【需填写】WxPusher token（SPT_xxx 或 AT_xxx）
WX_PUSHER_UIDS = []                # 【需填写】标准模式：关注应用后的 UID（SPT 模式留空）

# Server酱 密钥（可多个，依次推送）—— 注意：Server酱推到「微信服务通知」渲染差、易串行，
# 已不作为主力通道（默认不启用，仅在 DELIVERY_CHANNELS 显式包含 serverchan 时才用）。
SERVERCHAN_KEYS = []               # 【可选】Server酱 SendKey（SCT...）

# ===================== 运行参数 =====================
# 每天生成时间（仅做日志/去重参考，实际触发由网页后台 APScheduler 或系统定时任务控制）
RUN_HOUR = 6
LOG_FILE = os.path.join(LOG_DIR, f"{__import__('datetime').date.today():%Y-%m-%d}.log")

# ===================== 发送开关 =====================
# 默认仅生成早报并保存到 output/，不向任何通道发送（渠道密钥为空时也会自动禁用）。
# 在网页后台或 config.json 填好密钥并启用通道后，才会真正推送。
DELIVERY_ENABLED = True            # False=仅生成+保存本地；True=按下面通道发送
# 发送通道（DELIVERY_ENABLED=True 时生效，按填写情况自动启用可用通道）：
#   wxpusher ：WxPusher 极简/标准推送（直达个人微信·免注册·格式稳）→ 优先
#   wework   ：企业微信机器人 Webhook（已验证，格式稳定，作为备份）
#   serverchan：Server酱（推到个人微信服务通知，渲染差易串行，默认不启用）
#   dingtalk ：钉钉自定义机器人（企业协同场景）
#   wechat   ：文件传输助手/群（需微信降级+WeChatFerry，默认关）
DELIVERY_CHANNELS = ["wxpusher", "wework"]

# 钉钉机器人（网页后台 / config.json 填写；此处留空占位）
DINGTALK_WEBHOOK = ""              # 【需填写】钉钉机器人 Webhook（含 access_token）
DINGTALK_SECRET = ""               # 【可选】钉钉机器人加签 Secret（开启加签时填）

# ---------- 允许 config_local.py 覆盖任意配置（通用化关键）----------
try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass
