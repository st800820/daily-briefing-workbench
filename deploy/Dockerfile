# 早报工作台 · Docker 镜像（飞牛小主机 / 任意 Linux Docker 主机）
# 构建上下文为项目根目录：
#   docker build -f deploy/Dockerfile -t daily-briefing ..
# 或直接用 docker-compose（见 docker-compose.yml）。
FROM python:3.11-slim

# 时区设为上海，保证后台"06:30"是北京时间
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# 依赖（用 docker 专用精简清单，去掉 wcferry；含 Flask + APScheduler）
COPY deploy/requirements-docker.txt /app/requirements-docker.txt
RUN pip install --no-cache-dir -r /app/requirements-docker.txt

# 复制整个项目（src / config / docs / samples 等）
COPY . /app

# 后台监听端口（可用环境变量 ADMIN_PORT 覆盖）
ENV ADMIN_PORT=12345
EXPOSE 12345

# 启动网页后台（内置 APScheduler 负责每日定时，不再依赖 cron）
CMD ["python", "src/admin_app.py"]
