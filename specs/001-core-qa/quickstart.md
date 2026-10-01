# Quickstart — F1 核心问答（core-qa）验证指南

> 目标：本地起一套环境，跑通 spec 的 SC-001~008 验收场景。

## 前置

- Python 3.12+、Node 22+、PostgreSQL 16（含 pgvector 扩展；Docker 最省事）
- 云服务密钥：对话模型（DeepSeek 或 OpenAI）+ Embedding（硅基流动 或 阿里云百炼）

## 安装与运行

```bash
# 1) 数据库
cd deploy && docker compose up -d db

# 2) 后端
cd server
python -m venv .venv && source .venv/bin/activate
pip install -e .
alembic upgrade head
cp .env.example .env     # 填数据库 URL、对话模型/Embedding 密钥、单用户账号初始密码
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 3) 前端（构建静态产物，后端自动托管）
cd web && npm install && npm run build

# 4) 打开 http://localhost:8000 → 登录
```

> 开发模式：后端 `uvicorn --reload` + 前端 `npm run dev`（`NEXT_PUBLIC_API_URL` 指向后端）。

## 验证场景（对应 spec Success Criteria）

| # | 操作 | 预期结果 | 对应条目 |
|---|------|---------|---------|
| 1 | 上传一份 300 页内的文本型 PDF，计时 | 5 分钟内状态 `processing → indexed` 且可被检索 | SC-001 |
| 2 | 提问书中的细节 | 回答含出处：**资料名 + 位置 + 引用片段**，正文 [N] 编号可点击跳转原文 | SC-002 / FR-006 |
| 3 | 问一个完全的库外问题 | 回答标注"来自模型知识" | SC-003 / FR-007 |
| 4 | 重复问同一库外问题 | 命中"既往对话"（source_type=prior_conversation），无新模型调用 | SC-004 / FR-008 |
| 5 | 上传一份扫描版 PDF | 登记为"无法解析"（不拒绝），原文件可下载 | SC-007 / FR-014 |
| 6 | 下载任一资料原文件并比对校验和 | 与上传件一致（字节级） | SC-006 / FR-013 |
| 7 | Windows 浏览器"安装"；Android"添加到主屏幕" | 独立应用形态打开并完成一次问答 | SC-005 / FR-012 |
| 8 | 删除一份被旧对话引用过的资料，回看旧对话 | 引用处显示"来源已删除"，页面不报错 | spec 边界情况 |
| 9 | 触发一次备份并做恢复演练（恢复到临时库） | 数据完整可恢复；异地对象存储存在副本 | SC-008 |

## 自动化

- 单元/集成：`cd server && pytest`
- 验收（tasks 阶段生成）：`pytest tests/acceptance/` —— 场景 1-9 脚本化
