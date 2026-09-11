# 服务器部署

本目录记录当前 Ubuntu 服务器实际使用的 systemd 部署方式。服务文件固定使用：

- 用户和用户组：`ubuntu`
- 仓库目录：`/home/ubuntu/douyin-caption`
- 后端端口：`8000`
- 前端端口：`5173`

在其他服务器使用前，应先调整 `deploy/systemd/*.service` 中的用户、目录和可执行文件路径。

## 1. 运行环境

服务器需要 Python 3.12 或更高版本、Node.js、npm、PostgreSQL、Redis 和 systemd。当前服务文件要求 npm 位于 `/usr/bin/npm`。

生产环境的 `.env` 保存在仓库根目录，但不能加入 Git。至少检查以下配置：

```dotenv
APP_ENV=production
APP_SECRET_KEY=<独立生成的随机值，至少 32 个字符>
KEY_ENCRYPTION_SECRET=<独立生成的随机值，至少 32 个字符>
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<database>
REDIS_URL=redis://<host>:6379/0
ALLOW_IN_MEMORY_COORDINATION=false
CORS_ORIGINS=["https://<实际访问域名>"]
```

`APP_SECRET_KEY` 与 `KEY_ENCRYPTION_SECRET` 必须彼此独立。已有成员密钥数据时不能直接更换 `KEY_ENCRYPTION_SECRET`，否则已加密的 Provider 配置将无法读取。

## 2. 首次安装

在 `/home/ubuntu/douyin-caption` 中执行：

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -e backend
npm --prefix frontend ci
npm --prefix frontend run build
backend/.venv/bin/alembic -c alembic.ini upgrade head
```

确认 `.env` 已安全配置后安装服务：

```bash
sudo install -m 0644 deploy/systemd/douyin-caption-backend.service /etc/systemd/system/
sudo install -m 0644 deploy/systemd/douyin-caption-frontend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now douyin-caption-backend.service
sudo systemctl enable --now douyin-caption-frontend.service
```

## 3. 更新部署

部署前记录当前提交，并确认工作区没有只存在于服务器的源码修改：

```bash
git rev-parse HEAD
git status --short
```

先在仓库外创建仅部署用户可访问的备份目录，并备份 `.env`：

```bash
install -d -m 0700 /home/ubuntu/douyin-caption-backups
cp --preserve=mode,timestamps .env "/home/ubuntu/douyin-caption-backups/env-$(date +%Y%m%d-%H%M%S)"
```

PostgreSQL 使用 `pg_dump` 原生连接参数或受保护的 `.pgpass`/service 配置。不要把应用使用的 `postgresql+asyncpg://` 地址直接传给 `pg_dump`：

```bash
pg_dump --format=custom --dbname=caption --file="/home/ubuntu/douyin-caption-backups/caption-$(date +%Y%m%d-%H%M%S).dump"
```

如果当前部署使用 SQLite，应改用 SQLite 在线备份，不要在服务运行时直接复制数据库文件：

```bash
sqlite3 development.sqlite3 ".backup '/home/ubuntu/douyin-caption-backups/development-$(date +%Y%m%d-%H%M%S).sqlite3'"
```

确认备份成功后更新应用：

```bash
git pull --ff-only
backend/.venv/bin/python -m pip install -e backend
npm --prefix frontend ci
npm --prefix frontend run build
backend/.venv/bin/alembic -c alembic.ini upgrade head
sudo systemctl restart douyin-caption-backend.service
sudo systemctl restart douyin-caption-frontend.service
```

## 4. 验证与日志

```bash
systemctl --no-pager --full status douyin-caption-backend.service
systemctl --no-pager --full status douyin-caption-frontend.service
curl --fail http://127.0.0.1:8000/health
curl --fail --head http://127.0.0.1:5173/
journalctl -u douyin-caption-backend.service -n 100 --no-pager
journalctl -u douyin-caption-frontend.service -n 100 --no-pager
```

检查服务状态之外，还应使用普通成员账号验证登录、方案选择、AI 队列和版本生成流程。

## 5. 回滚原则

部署前必须记录旧提交 SHA 并保留数据库备份。应用回滚后重新安装该提交对应的 Python 和 Node 依赖并重新构建前端。数据库迁移不能盲目执行 `alembic downgrade`；先确认目标提交的数据结构兼容性，不兼容时使用部署前备份恢复数据库。

## 当前限制

前端 systemd 服务使用 `vite preview`，目的是与当前服务器运行状态保持一致。它不是面向公网的强化生产服务器。正式接入域名和 HTTPS 时，应在单独任务中改用 Nginx 或 Caddy 托管 `frontend/dist`，代理 `/api` 到后端，并只开放反向代理端口。
