# 部署指南（Docker / 飞牛小主机）

本目录提供将「每日早报工作台」容器化的交付物，适合在**飞牛小主机（fnOS）**或任意 Linux Docker 主机上 7×24 无人值守运行。

## 文件说明

- `Dockerfile`：基于 `python:3.11-slim`，安装精简依赖后启动网页后台。
- `docker-compose.yml`：编排服务，挂载 `config.json` / `output/` / `logs/` 到宿主机，暴露端口 `12345`。
- `requirements-docker.txt`：容器依赖（Flask + APScheduler + requests + Pillow，不含 wcferry）。

## 一键部署

```bash
# 1. 准备配置（必须存在，Docker 挂载需要真实文件）
cp config.example.json config.json
# 编辑 config.json 填入你自己的密钥（或用启动后的网页后台填写）

# 2. 构建并后台启动（在项目根目录执行）
docker compose -f deploy/docker-compose.yml up -d --build

# 3. 查看日志
docker compose -f deploy/docker-compose.yml logs -f

# 4. 浏览器访问 http://<主机IP>:12345
```

## 飞牛（fnOS）实操要点

1. **传文件**：把整个项目目录上传到飞牛（文件应用 / SMB / `scp`），解压得到项目根目录（内含 `config.json`）。
2. **镜像源**：国内拉取 `python:3.11-slim` 若报 `401` / 超时，请先在 fnOS 的 Docker 设置里配置国内镜像源
   （如 `https://docker.m.daocloud.io`、`https://hub-mirror.c.163.com`），保存后重启 Docker 守护进程再重试。
3. **SSH 构建**：在飞牛开启 SSH 后登录，`cd` 进项目根目录执行上面的 `docker compose ... up -d --build`。
4. **访问**：查飞牛内网 IP（设置 → 网络），浏览器开 `http://飞牛IP:12345`。

## 日常运维

| 目的 | 命令 |
|---|---|
| 启动 / 重建 | `docker compose -f deploy/docker-compose.yml up -d --build` |
| 停止 | `docker compose -f deploy/docker-compose.yml down` |
| 看实时日志 | `docker compose -f deploy/docker-compose.yml logs -f` |
| 改配置生效 | 网页后台保存即生效（写回宿主机 `config.json`）；改 `src/config.py` 需重建容器 |

## 安全提醒

- 后台端口 `12345` 不要裸奔公网；如需外网访问请加反向代理 + `ADMIN_PASSWORD`（用环境变量注入，勿明文写死）。
- 真实 `config.json` 含密钥，**不要提交到公开仓库**（已写入根目录 `.gitignore`）。
