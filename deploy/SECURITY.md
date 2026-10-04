# 安全配置与密钥清单（T034）

> 本文件是部署与运维的安全基线。T035 部署时逐项执行；日常改动涉及密钥/认证时回来更新。

## 密钥 / 凭据清单

**原则：密钥只存在于服务器端 `server/.env` 与服务器本地文件，绝不进 git。** 仓库只有 `.env.example`（占位符）。

| 名称 | 位置 | 用途 | 丢失/泄露后果与轮换 |
|------|------|------|---------------------|
| `ADMIN_PASSWORD` | `server/.env` | 登录密码（单用户） | 部署首日改成强密码；轮换即重新登录 |
| `SECRET_KEY` | `server/.env` | 会话 Cookie 签名 | 泄露=可伪造会话；轮换使全部会话失效（重新登录即可）。生成：`openssl rand -hex 32` |
| `DATABASE_URL` 内密码 | `server/.env` / compose | Postgres | 数据库不对公网开放，风险低 |
| `EMBEDDING_API_KEY` | `server/.env` | 硅基流动 | 可在控制台吊销重建 |
| `LLM_API_KEY` | `server/.env` | DeepSeek | 同上 |
| `~/.config/second-brain/backup.key` | 服务器本地（600）+ **密码管理器离线副本** | 备份加密（零知识） | **丢失 = 全部备份作废（不可再生！）** —— 唯一需要"离线多处"的凭据 |
| （部署阶段）对象存储子账号密钥 | 部署时新增 | 异地备份 | 用最小权限子账号（仅目标桶读写）；见 R8 |

## 登录限速（T034 已实现；T093 加固）

- 默认**双键**：同一 `IP + 用户名` 15 分钟内失败 **5** 次；同一 **IP** 15 分钟内失败 **10** 次（**防随机用户名绕过**）→ HTTP 429 + `Retry-After`（`LOGIN_RATE_LIMIT` / `LOGIN_RATE_LIMIT_IP` / `LOGIN_RATE_WINDOW_MIN` 配置）
- 用户名/密码长度上限（64/256 字符，超长 → 422）——防限速器键膨胀与 argon2 开销放大
- 实现：进程内滑动窗口（`server/app/auth/ratelimit.py`）；多进程/多用户化时替换为 Redis（接口已隔离）
- ⚠️ 反代后方：uvicorn 需以 `--proxy-headers --forwarded-allow-ips=<反代IP>` 启动，否则按反代 IP 限速全局

## 信息暴露面（T093）

- `/docs` `/redoc` `/openapi.json` **默认关闭**（未认证的 API 结构暴露）；本地调试 `DOCS_ENABLED=true` 临时开启，生产保持关闭
- MCP DNS-rebinding 白名单默认仅本机（`localhost`/`127.0.0.1`）；局域网/域名访问经 `MCP_ALLOWED_HOSTS`（逗号分隔、含端口）显式配置
- SPA 回退路由已做路径边界校验（T092，防 `..` 穿越读任意文件）

## deploy/.env（compose 必填项，T093）

`deploy/docker-compose.yml` 的 `POSTGRES_PASSWORD` / `SEARXNG_SECRET` **无默认值**（防弱口令部署）——
先在 `deploy/.env`（已 gitignore）设置，再 `docker compose up`：

```sh
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" > deploy/.env
echo "SEARXNG_SECRET=$(openssl rand -hex 32)" >> deploy/.env
```

（已初始化过的数据库：`POSTGRES_PASSWORD` 改动不会生效——initdb 只在首次建卷时写入；保持原值或重建卷。）

## HTTPS 完整步骤（部署执行，T035 展开细节）

1. 域名 A 记录解析到服务器 IP
2. 安装 Caddy，`Caddyfile`：
   ```
   你的域名 {
       reverse_proxy 127.0.0.1:8000
   }
   ```
   Caddy 自动申请/续期 Let's Encrypt 证书并 80→443 跳转
3. uvicorn 启动参数：`--proxy-headers --forwarded-allow-ips=127.0.0.1`
4. `server/.env`：`AUTH_COOKIE_SECURE=true`；`SECRET_KEY=$(openssl rand -hex 32)`
5. 防火墙仅开放 **80/443**（SSH 视需要）；Postgres 端口不对公网
6. 验证：`https://域名` 可登录；Cookie 属性含 `Secure; HttpOnly`；`http://` 自动跳 `https://`

## 安全检查清单（部署核对）

- [ ] `ADMIN_PASSWORD` 已改为强密码
- [ ] `SECRET_KEY` 已随机化（非默认值，≥32 字符——启动 fail-closed 校验）
- [ ] `deploy/.env` 已设置（compose 必填：POSTGRES_PASSWORD / SEARXNG_SECRET）
- [ ] `/docs` `/openapi.json` 生产环境不可访问（默认关闭）
- [ ] 登录限速生效（连续失败 5 次收到 429；换随机用户名后失败 10 次同样 429）
- [ ] HTTPS 生效 + Cookie `Secure` 标志
- [ ] 防火墙最小开放（80/443）
- [ ] 备份密钥离线副本已存（密码管理器 + 手写）
- [ ] 对象存储用最小权限子账号（部署阶段）
