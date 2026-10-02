# 服务器部署手册（T035）

> **目标**：一台全新 Ubuntu 服务器 → 30 分钟内跑起 HTTPS 可访问的 second-brain。
> **形态**：Postgres 用 Docker；应用用 **venv + systemd**（2C4G 内存友好、升级简单）；Caddy 负责自动 HTTPS。
> **备选（未采用）**：全容器化——服务器上构建含 torch/Docling 的应用镜像吃内存与磁盘，且升级需重建镜像。
> **安全基线**：逐项对照 [`SECURITY.md`](./SECURITY.md) 的核对清单；备份细节见 [`backup/README.md`](./backup/README.md)。

## 0. 前置

- Ubuntu 22.04+（2C4G 起步）；域名 A 记录已指向服务器 IP
- 下文命令默认使用国内镜像；`<仓库地址>` / `your-domain.example` 处按实际替换

## 1. 基础环境（约 5 分钟）

```bash
# Docker（用于 Postgres 与备份脚本）
curl -fsSL https://get.docker.com | sh
sudo mkdir -p /etc/docker && cat <<'EOF' | sudo tee /etc/docker/daemon.json
{ "registry-mirrors": ["https://docker.m.daocloud.io"] }
EOF
sudo systemctl restart docker

# Python 3.12 + Node 22 + git
sudo apt update && sudo apt install -y python3.12 python3.12-venv git curl
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
npm config set registry https://registry.npmmirror.com

# Caddy（HTTPS 反代）
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

> 若 cloudsmith 拉不动：改用 Caddy 官方 GitHub Release 的静态二进制（经镜像下载后放 `/usr/local/bin/caddy` 并自建 systemd 单元）。

## 2. 拉代码与数据库（约 3 分钟）

```bash
sudo git clone <仓库地址> /opt/second-brain
cd /opt/second-brain

# 数据库密码（务必改强密码；compose 会读取 deploy/.env）
echo 'POSTGRES_PASSWORD=<换成强密码>' | sudo tee deploy/.env
sudo docker compose -f deploy/docker-compose.yml up -d
```

## 3. 应用与前端（约 10 分钟，Docling 等依赖下载为主）

```bash
cd /opt/second-brain/server
python3.12 -m venv .venv && source .venv/bin/activate
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip install -e .

cp .env.example .env    # 逐项填写：
#   DATABASE_URL       → postgresql+asyncpg://secondbrain:<上面的强密码>@localhost:5433/secondbrain
#   ADMIN_PASSWORD     → 登录密码（强密码）
#   SECRET_KEY         → openssl rand -hex 32 生成
#   EMBEDDING_API_KEY / LLM_API_KEY → 硅基流动 / DeepSeek 密钥
#   AUTH_COOKIE_SECURE → true（HTTPS 部署）

.venv/bin/alembic upgrade head

# 前端构建（产物 web/out 由后端托管）
cd /opt/second-brain/web && npm ci && npm run build
```

## 4. systemd 自启（约 2 分钟）

```bash
sudo cp /opt/second-brain/deploy/second-brain.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now second-brain
systemctl status second-brain --no-pager    # 应为 active (running)
```

## 5. Caddy HTTPS（约 2 分钟）

```bash
sudo cp /opt/second-brain/deploy/Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/your-domain.example/你的域名/' /etc/caddy/Caddyfile
sudo systemctl reload caddy
# 验证：浏览器打开 https://你的域名 → 登录页（证书自动签发，首次约 10 秒）
```

## 6. 备份定时（约 2 分钟）

```bash
# 生成备份密钥并抄进密码管理器（丢失 = 备份作废！）
mkdir -p ~/.config/second-brain && chmod 700 ~/.config/second-brain
openssl rand -base64 32 | tr -d '\n' > ~/.config/second-brain/backup.key
chmod 600 ~/.config/second-brain/backup.key
cat ~/.config/second-brain/backup.key   # ← 立刻存进密码管理器

crontab -e   # 加入两条（路径按服务器实际）：
# 17 3 * * * SECOND_BRAIN_BACKUP_STALE_ONLY=1 /opt/second-brain/deploy/backup/backup.sh >> /opt/second-brain/server/data/backups/backup.log 2>&1
# @reboot sleep 90 && SECOND_BRAIN_BACKUP_STALE_ONLY=1 /opt/second-brain/deploy/backup/backup.sh >> /opt/second-brain/server/data/backups/backup.log 2>&1
```

## 7. 防火墙（约 1 分钟）

```bash
sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw enable
# Postgres 仅绑定 127.0.0.1（compose 已配置），uvicorn 仅监听 127.0.0.1（systemd 单元已配置）
```

## 8. 验收（对照 quickstart 逐项）

```bash
cd /opt/second-brain/server
.venv/bin/pytest tests/acceptance/ -v
# 期望：6 passed, 1 skipped（安装类场景为真机手动项）
```

真机手动项：手机 Chrome/Edge 打开 `https://你的域名` → 「安装应用」→ 无地址栏独立形态；备份密钥离线副本已存。

## 9. 日常升级

```bash
cd /opt/second-brain && git pull
cd server && .venv/bin/pip install -e . && .venv/bin/alembic upgrade head
cd ../web && npm ci && npm run build
sudo systemctl restart second-brain
```

## 附录

- **异地备份**：部署时与服务器同厂同地域开对象存储桶（OSS/COS），rclone 上传 `server/data/backups/` 中的密文（见 research R8；配置步骤在买定厂商后补充本节）
- **回滚**：`git checkout <上一个可用 commit>` 后按「日常升级」的后半段执行
- **故障排查**：`journalctl -u second-brain -n 100`（应用日志）/ `systemctl status caddy`（HTTPS）/ `docker compose -f deploy/docker-compose.yml logs db`
