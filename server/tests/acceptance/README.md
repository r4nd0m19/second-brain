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

## 运行

```bash
cd server
.venv/bin/pytest tests/acceptance/ -v          # 全套（约 8-10 分钟，会真实调用 LLM/embedding）
.venv/bin/pytest -m "not acceptance"           # 只跑单元测试
```

**前置条件**：服务已启动（`SECOND_BRAIN_BASE_URL` 可覆盖，默认 localhost:8000）；sc002 用例要求库中已入库 ≥2 份样本书，否则该用例 skip；SC-008 需要 docker 数据库在跑。

**测试卫生**：所有用例自带清理（删除上传文档、评测对话及其兜底回写）；服务不可达时整套 skip，不影响单元测试。
