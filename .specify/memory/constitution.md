# second-brain Constitution

> 本文件是项目的治理原则。speckit 的 specify / plan / tasks / implement 四个命令每次执行都会读取它。
> 结构说明：**Core Principles 为通用 SDD 标准（项目无关，未来会提炼进 sdd-standard 标准件）；Project Principles 为本项目专属。**

## Core Principles（通用 SDD 标准）

### I. 文档结构合规（NON-NEGOTIABLE）

所有 SDD 文档（spec.md / plan.md / tasks.md）必须遵循 `.specify/templates/` 中的定制模板结构：

- 带 *(mandatory)* 标记的节必须保留并填写；删除或跳过任何节/子节必须经用户明确确认
- plan.md 必须包含「设计决策与理由」节
- tasks.md 的每个任务必须包含 `Deps:` 与 `DoD:` 子项

### II. 决策留痕与调研先行（NON-NEGOTIABLE）

每个非平凡决策（技术选型、架构、数据模型、接口设计、测试策略）必须按顺序完成三步：

1. **先调研**：联网核实当前最佳实践、成熟先例、行情/版本/兼容性等事实，不得凭记忆拍板；调研来源随决策记录
2. **再征询**：有实质权衡的决策先通过 decision-consult 协议征询用户，再落入文档
3. **后记录**：结论 / 理由 / 备选方案及放弃原因

禁止代替用户拍板后补记；纯偏好类、无外部事实可查的小决策可跳过调研。

### III. 文档语言

项目文档（spec / plan / tasks / project.md / constitution）使用中文；代码、标识符、专有名词保持原文。

## Project Principles（second-brain 专属）

### IV. 数据最小暴露

个人数据（浏览记录、私人对话、上传文件）敏感度最高：

- 数据全量存于自租服务器（2026-10-01 决策：不做本地孤岛，保证双端一致可见），不引入第三方数据 SaaS
- 防护：传输 TLS + 服务器磁盘加密 + 强认证
- 采集黑名单：用户标记的站点/类别从源头不采集（不产生数据优于事后删除）
- 调用外部模型时，只发送检索命中的必要片段，不整库外发

### V. 数据可控

- 可删除任意单条入库内容；可按时间范围清理（如某段浏览记录）
- 删除必须在备份策略中同步生效
- 已入库数据可导出

### VI. 可靠性优先于花哨

- 备份机制是 v1 的组成部分，不是后续优化
- 采集器（尤其 ChatGPT 采集，依赖平台接口）失效时，不得影响核心问答的可用性 —— 采集与问答必须解耦

### VII. 单人规模，留扩展余地

- 按单人使用设计最优解；不为多用户/规模化增加 v1 复杂度
- 架构决策为将来留余地（如大脑作为独立服务、数据模型不过度耦合单场景）

## Governance

- 本 constitution 优先于其他实践约定；与 docs 冲突时以本文件为准
- 修订流程：说明原因 → 用户批准 → 语义化更新版本号
- `/speckit-plan` 的 Constitution Check 必须逐条验证上述原则；违反项必须记录在 plan.md 的 Complexity Tracking 中并说明正当理由

**Version**: 1.0.0-draft | **Ratified**: 待用户批准（2026-10-01 起草） | **Last Amended**: 2026-10-01
