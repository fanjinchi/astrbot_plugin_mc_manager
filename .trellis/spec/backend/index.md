# Backend Development Guidelines

> Best practices for backend development in this project.

---

## Overview

这是 AstrBot 的 Minecraft 服务器管理插件（单仓库、单 Python 包、无数据库、无 Web 服务）。这份 spec 描述的是
**代码当前真实的样子**，不是理想架构；改代码前先按下面索引读对应文件。

规格注入方式：任务的 `implement.jsonl` / `check.jsonl` 决定子代理看到哪些文件；所以文件名与索引保持一致。

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | 目录布局、三层职责、依赖方向、新功能改动清单、命名 | Filled |
| [Database Guidelines](./database-guidelines.md) | 无数据库；状态落在 MC 侧/AstrBot 配置/进程内存的规则 | Filled |
| [Error Handling](./error-handling.md) | 双错误面、RCON 重试、返回值格式、裸 except 边界 | Filled |
| [Quality Guidelines](./quality-guidelines.md) | LLM 工具契约、禁止/必用模式、验证方式、已知债务、提交约定 | Filled |
| [Logging Guidelines](./logging-guidelines.md) | logger 来源、级别用法、消息格式、不该记什么 | Filled |

配套的通用思维指南在 [../guides/](../guides/index.md)（已预填，未按本项目定制）。

---

## 先读哪个

| 你要做的事 | 先读 |
|---|---|
| 新增/修改 LLM 工具 | quality-guidelines（工具契约）→ directory-structure（改动清单）→ error-handling |
| 改日志监控链路 | logging-guidelines → directory-structure |
| 改配置项 | database-guidelines（配置落点）→ quality-guidelines（第 7 条） |
| 不确定代码放哪 | directory-structure |

---

## How to Fill These Guidelines

这些文件已完成首次填充（来源：仓库真实代码 + 历史决策）。后续维护规则：

1. 记录**实际做法**，不写"应该怎样"；团队已知技术债写进 quality-guidelines 的"已知债务"，不与理想混写。
2. 每条规则尽量带**真实文件:行号**，让子代理能点开对照。
3. 新增禁止项时说明原因和现实场景，不要写没有触发条件的教条。
4. 改动本目录时同步更新本索引的 Status/描述。

---

**Language**: 正文用中文（与仓库 README、注释、Trellis 任务文档一致）；标题沿用模板英文骨架。
