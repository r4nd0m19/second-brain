# 实现前需求质量审查 Checklist: F1 核心问答（core-qa）

**Purpose**: 在实施开始前，对 spec / plan / tasks / data-model / contracts 的**需求质量**做全面审查 —— 相当于"用英语写的单元测试"：检验需求本身是否完整、清晰、一致、可测，而不是检验实现是否正确
**Created**: 2026-10-01
**Feature**: [spec.md](../spec.md)（配套 plan.md / tasks.md / data-model.md / contracts/api.md / research.md）

**Note**: 本清单由 `/speckit-checklist` 生成，供人工逐项审查。
**Review Ownership**: 评审者所有 —— 只有你确认某项"需求质量达标"才勾选 `[x]`
**Marker Semantics**: `[x]` = 该项需求质量已审查通过，**不代表实现完成**；未勾选项 = 待修改/待澄清清单

## Requirement Completeness（需求完整性）

- [ ] CHK001 空状态需求是否定义：空库首次提问、无会话、资料列表为空时的行为？ [Gap]
- [ ] CHK002 界面语言是否有需求规定（文档为中文，但 UI 语言未写明）？ [Gap]
- [ ] CHK003 同一账号多设备同时使用时，会话与状态的行为是否定义为需求？ [Coverage, Gap]
- [ ] CHK004 删除需求（FR-011）是否覆盖全部内容类型：资料 / 对话 / 原文件 / 检索索引 / 备份副本？ [Completeness, Spec §FR-011]
- [ ] CHK005 整库导出需求是否存在，还是仅有"删除权"？（数据可携带性） [Gap]
- [ ] CHK006 "无法解析"文件在资料列表之外的可见入口（如筛选/统计）是否有要求？ [Gap]

## Requirement Clarity（清晰度）

- [ ] CHK007 "强认证"是否量化为可验证标准（密码策略 / 会话时长 / 登录限速）？ [Ambiguity, Spec §NFR Security]
- [ ] CHK008 "无明显降级"（10 万块规模）是否给出可测量阈值？ [Clarity, Spec §NFR Performance]
- [ ] CHK009 "弱相关"的判定阈值或规则是否定义（分数阈值 / 语义规则）？ [Ambiguity, Spec §FR-007]
- [ ] CHK010 "无法解析"的判定标准（无文本层 / 格式不支持 / 损坏文件）是否有可执行规则？ [Clarity, Spec §FR-014]
- [ ] CHK011 回答中引用片段（quote）的长度上限是否定义？ [Gap, Spec §FR-006]
- [ ] CHK012 对话标题"取首问前 N 字"的 N 是否定义？ [Gap, data-model]
- [ ] CHK013 "10 秒内开始流式回复"是否同时适用于命中路径与兜底路径（还是仅其一）？ [Clarity, Spec §NFR]

## Requirement Consistency（一致性）

- [ ] CHK014 资料/对话的界面分区（FR-009）、删除位置（FR-011）、检索互通 三处表述是否一致？ [Consistency, Spec §FR-009/011]
- [ ] CHK015 解析状态枚举（处理中 / 已入库 / 无法解析）在 spec、data-model、contracts 是否完全一致？ [Consistency]
- [ ] CHK016 US2→US3 的依赖链条（先有兜底才有回写）与"每个 story 独立可测"的原则是否已协调（如：手工构造对话记录即可独立测 US3）？ [Consistency, Spec §US3]
- [ ] CHK017 双端可用（FR-012）与采集边界（Non-Goals：手机仅 Firefox）表述之间是否无冲突？ [Consistency]

## Acceptance Criteria Quality（验收标准质量）

- [ ] CHK018 SC-002 的"一组样例问题"是否定义（数量 / 来源 / 评分方式）？ [Measurability, Spec §SC-002]
- [ ] CHK019 SC-004"不触发外部模型调用"的验证方法是否明示（日志 / 来源标注）？ [Measurability, Spec §SC-004]
- [ ] CHK020 SC-008"恢复演练通过"的判定标准是否具体（恢复哪些数据、校验什么）？ [Measurability, Spec §SC-008]
- [ ] CHK021 全部成功标准是否无需了解实现细节即可验证？ [Measurability, Spec §SC]

## Scenario Coverage（场景覆盖）

- [ ] CHK022 部分失败恢复：入库中断（embedding 失败 / 进程重启）后的**幂等重试**要求是否定义？ [Coverage, Gap]
- [ ] CHK023 批量/并发上传多个文件的处理（排队 / 并行 / 顺序）是否有需求？ [Coverage, Gap]
- [ ] CHK024 超长对话的上下文截断策略是否有需求（多轮何时开始丢弃历史）？ [Coverage, Gap]
- [ ] CHK025 误删保护：删除操作是否需要确认或短时撤销？ [Coverage, Gap]

## Edge Case Coverage（边界情况）

- [ ] CHK026 0 字节空文件的上传行为是否定义？ [Edge Case, Gap]
- [ ] CHK027 加密 PDF / 带密码文档是否归入"无法解析"路径？ [Edge Case, Gap]
- [ ] CHK028 数据库或磁盘空间耗尽的处理要求是否存在？ [Edge Case, Gap]
- [ ] CHK029 文件名含特殊字符 / 超长时的存储与下载名称规则是否定义？ [Edge Case, Gap]

## Non-Functional Requirements（非功能需求质量）

- [ ] CHK030 备份的 RPO（可接受的数据丢失窗口）是否明示（每日备份隐含 ≤24h，需写实）？ [NFR, Gap, Spec §SC-008]
- [ ] CHK031 性能目标是否覆盖全链路各阶段（上传 / 解析 / 检索 / 生成），还是仅生成阶段？ [NFR, Spec §NFR]
- [ ] CHK032 "调用外部模型仅发送命中片段"是否有可核查的表述（否则无法验收）？ [NFR, Spec §NFR Security]

## Dependencies & Assumptions（依赖与假设）

- [ ] CHK033 Docling 对目标格式（中文 PDF / EPUB）的解析质量假设，是否列为待实测验证项？ [Assumption, research.md]
- [ ] CHK034 云 embedding 提供商（硅基流动免费额度等）条款变更风险与"接口可替换"对策是否记为假设？ [Assumption]
- [ ] CHK035 2C4G 服务器规格与"10 万块检索 + 解析并发"的能力假设是否记录为待验证？ [Assumption]

## Ambiguities & Traceability（遗留模糊与追溯）

- [ ] CHK036 全文是否无遗留 [NEEDS CLARIFICATION] / TODO / 占位符？ [Consistency]
- [ ] CHK037 术语一致性："资料（Document）"作为规范术语，是否在 spec / plan / tasks 中统一（未混用"文档/文件"指代同一实体）？ [Traceability]
- [ ] CHK038 每个 FR 是否可追溯到 ≥1 个任务，且每个任务可回溯到 FR/SC 或明确标注为 NFR/部署支撑？ [Traceability]

## Notes

- 勾选 `[x]` 仅在你确认该项**需求质量**达标之后；未勾选项即"实施前建议修正"清单
- `/speckit-implement` 会把未勾选项作为提醒（gate），但不会代改标记
- `checklists/requirements.md` 是另一份内置规格质量清单（由 specify/clarify 维护），与本清单互不干扰
- 建议审查顺序：先看 Requirement Clarity（CHK007-013，最容易引发返工），再扫 Consistency 与 Acceptance Criteria
- 审查结论可写在本文件末尾（findings 内联即可）
