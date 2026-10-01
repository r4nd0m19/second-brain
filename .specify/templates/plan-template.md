# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]

**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

<!--
  结构约束：本模板中标 *(mandatory)* 的节必须保留并填写；删除或跳过任何节/子节必须经用户确认。
  依据：.specify/memory/constitution.md「文档结构合规」原则。
-->

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]

**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]

**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]

**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]

**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]

**Project Type**: [e.g., library/cli/web-service/mobile-app/compiler/desktop-app or NEEDS CLARIFICATION]

**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]

**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]

**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## 设计决策与理由 (Design Decisions & Rationale) *(mandatory)*

<!--
  ACTION REQUIRED: 本节每一项选择都必须附理由与备选方案 —— 这是项目 constitution 的硬性要求。
  有实质权衡的决策（技术选型/架构/数据模型/接口）必须先联网调研、再通过 decision-consult 协议征询用户，然后记录于此；调研来源随决策记录。
  详细设计由 Phase 0/1 产出：数据模型→data-model.md，接口→contracts/，研究结论→research.md；此处记录关键决策与理由。
-->

### 技术栈选择
| 选择项 | 结论 | 理由 | 备选方案及放弃原因 |
|--------|------|------|--------------------|
| [语言/框架/库/工具] | [定什么] | [为什么] | [考虑过什么，为什么不用] |

### 架构选择
- **结论**: [架构方案；与 .specify/memory/project.md §9 总体架构的关系]
- **理由**: [为什么]
- **备选方案及放弃原因**: [对比过什么]

### 数据模型决策
- [关键建模决策 + 理由（详细字段/关系见 data-model.md）]

### 接口设计决策
- [关键接口/命令/格式决策 + 理由（详细契约见 contracts/）]

### 错误处理策略
- [错误处理方式 + 理由：哪些错误如何暴露给用户/调用方，如何恢复，如何记录]

### 测试策略
- **策略**: [测试层级与覆盖重点、工具、哪些必须测/哪些不测]
- **理由**: [为什么这样测]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

[Gates determined based on constitution file]

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
