# 验收测试（T032）

对**运行中的真实服务**做 HTTP 端到端验收，覆盖 quickstart 场景 1-9。

## 覆盖映射

| quickstart 场景 | 自动化 | 位置 |
|-----------------|--------|------|
| 1 上传 PDF → indexed（SC-001） | ✅ + 带出处提问 | `test_quickstart_scenarios.py::test_sc001_...` |
| 2 提问含出处（SC-002） | ✅ 样例题集 87% 通过率 | `test_sc002_eval.py`（包裹 `sc002_eval.py`） |
| 3 库外兜底（SC-003） | ✅ | `test_sc003_sc004_fallback_and_recall` |
| 4 二次命中（SC-004） | ✅ | 同上 |
| 5 扫描版登记（SC-007） | ✅ | `test_sc007_unparseable_registered` |
| 6 下载校验（SC-006） | ✅ | `test_sc006_download_checksum` |
| 7 双端安装（SC-005） | ⏭️ 手动（skip 注明） | 需 HTTPS + 真机 |
| 8 已删资料引用提示 | ⏭️ 前端手动（view 页 404 分支已实现） | — |
| 9 备份恢复演练（SC-008） | ✅ | `test_sc008_backup.py` |

## F2 浏览器采集（`test_capture_scenarios.py`）

| 场景 | 自动化 | 位置 |
|------|--------|------|
| 采集 → 问答命中且出处含链接/时间（SC-001） | ✅ | `test_sc001_capture_ask_and_replay` |
| 快照回放（CSP sandbox + gzip 直出，SC-008 原型） | ✅ | 同上 |
| 恶意 HTML 回放被沙箱隔离（T043 安全复核） | ✅ | `test_sc008_replay_hostile_html_is_contained` |
| 黑名单域名服务端零行（SC-003 服务端语义） | ✅ | `test_sc003_blocked_domain_zero_rows` |
| 删除后检索/出处同步消失、快照 404（SC-004） | ✅ | `test_sc004_delete_removes_from_recall` |
| 时间清单 + 语义×时间组合检索（SC-007，含 meta 时间范围回显） | ✅ | `test_sc007_time_lookup_list_and_search` |
| 扩展自动触发 / 黑名单源头拦截 / 断网补传 / 无感（SC-005/006） | ⏭️ Windows 真机手动（T045） | quickstart §2–6 |

## 运行

```bash
cd server
.venv/bin/pytest tests/acceptance/ -v          # 全套（约 8-10 分钟，会真实调用 LLM/embedding）
.venv/bin/pytest -m "not acceptance"           # 只跑单元测试
```

**前置条件**：服务已启动（`SECOND_BRAIN_BASE_URL` 可覆盖，默认 localhost:8000）；sc002 用例要求库中已入库 ≥2 份样本书，否则该用例 skip；SC-008 需要 docker 数据库在跑。

**测试卫生**：所有用例自带清理（删除上传文档、评测对话及其兜底回写）；服务不可达时整套 skip，不影响单元测试。
