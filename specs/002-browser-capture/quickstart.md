# Quickstart — F2 浏览器采集（验收指南）

> 前置：F1 可运行（`server/.venv/bin/uvicorn app.main:app --port 8000`、Postgres 容器、`web/out` 已构建）。
> 覆盖：安装 → 自动采集 → 隐私可控 → 离线容错 → 时间回找 → 快照保真 → 自动化回归（逐条对应 SC）。

## 1. 准备与安装

```bash
cd server && .venv/bin/alembic upgrade head        # 新迁移：documents 扩展列 + capture_tokens
.venv/bin/uvicorn app.main:app --port 8000         # 或既有启动方式

cd ../extension && npm ci && npm run build         # 产物 extension/dist
```

- Web UI（登录后）：「采集凭据」区块 → 新建（如 "Windows Chrome"）→ **复制 token（仅显示一次）**
- Chrome/Edge → `chrome://extensions`（或 `edge://extensions`）→ 开发者模式 → Load unpacked → 选 `extension/dist`
- Options：填 Server URL + token → 「保存并测试」→ 显示已连接

## 2. 自动采集（SC-001）

浏览一篇普通文章并真实阅读（停留 ≥10s 或滚动过半）→ 打开对话问其中细节 → **30 秒内**回答正确、出处为网页（标题 / 链接 / 浏览时间）。快速跳转（未达阈值）不产生条目。

## 3. 隐私与可控（SC-003 / SC-004）

- 黑名单加入某域名 → 访问并停留 → `GET /api/documents?source=browser` 无任何该域名条目（含元信息）
- 一键暂停 → 浏览 → 无新条目；恢复后继续工作
- 删除一条 → 对话检索与出处同步消失；快照不可达（404）

## 4. 离线容错（SC-005）

停服 → 正常浏览 2–3 页（badge 变黄、队列积压）→ 约 30 分钟后恢复服务 → 队列自动补传、无丢失（列表核对）。

## 5. 时间回找（SC-007）

- "我昨天 / 上周看过哪些网页？" → 清单正确（标题 + 时间）
- "上周看过的文章里关于 X 的部分" → 命中且时间过滤生效（回答回显时间范围，如"统计 9-21 ~ 9-27"）

## 6. 快照保真与安全（SC-008）

- 原链接失效或内容改版后 → 「查看快照」仍可看到当初内容
- 回放页无脚本执行、无外链请求（DevTools 核对）；超 20MB 的页面列表标注"未保留快照"（仅正文可检索）
- （可选）体积观测：`GET /api/documents?source=browser` 的 `snapshot.bytes` 抽样记录

## 7. 自动化回归

```bash
cd server && .venv/bin/pytest tests/acceptance/ -v   # 含 F2 新增场景
```

## 预期结果汇总

| 项 | 对应 SC | 判定标准 |
|----|---------|----------|
| 阅读后 30 秒内可问出细节 | SC-001 | 100% 抽样通过 |
| ≥3 天前浏览网页的 ≥10 题样例 | SC-002 | ≥80% 找回正确且出处正确 |
| 黑名单站点零采集 | SC-003 | 抽查 100% |
| 删除后检索 / 出处同步消失 | SC-004 | 100% 抽检 |
| 断服 30 分钟内容恢复后全补传 | SC-005 | 100% 补传 |
| 浏览体验无感 | SC-006 | 主观无感 + 无阻塞等待 |
| 时间类问题与实际行动一致 | SC-007 | 抽样核对 |
| 链接失效 / 改版后快照可看 | SC-008 | 抽检 100% |

> 失败清理：吊销凭据 `DELETE /api/capture/tokens/{id}`；清实验数据 `DELETE /api/documents?source=browser&…`（详 [contracts/capture-api.md](./contracts/capture-api.md)）。
