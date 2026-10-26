# KubeJS 模组命令结构化导出

## Goal

扩展现有 KubeJS runtime dump，从服务端真实命令树生成结构化命令快照，并让 `search_mc_commands` 能搜索命令名及当前 dispatcher 已注册的完整 usage 路径；已注册路径不代表当前调用者必然可执行。

## Background

- 父任务：`.trellis/tasks/10-25-mod-command-kb`，来源 Issue #5。
- `assets/runtime_dump.js:61` 当前仅导出 item/block/entity/fluid；`runtime_dump.py:130` 已提供部署、触发和 `[rd] DONE` 回执编排。
- `kb/commands.py:50` 只有 `data_dir/runtime_dump/commands.jsonl` 消费入口，仓库中没有模组命令生产者。
- 已确认语法级 MVP，允许 `source="unknown"` 与 `level=null`，不做额外语义描述库。
- CTI0.46 与 Farming 均已获部署、reload 和启动实测授权。

## Requirements

- **R1 运行时权威性**：在 `/researchdump` 执行时访问当前服务端 dispatcher，避免在命令注册尚未完成时提前快照。
- **R2 完整 usage**：按当前 dispatcher 已注册路径导出完整 literal/argument usage，不得仅导出顶层命令名或根级 smart usage；redirect 必须显式标识，不得伪装成可直接执行的命令字符串。完整 usage 不保证当前 RCON/玩家可执行，实际执行仍受 `requires`、source 类型和执行体内部玩家检查限制；参数可选性、类型和范围不属于本 API 能提供的数据。
- **R3 复现现有链路**：复用脚本部署、按需 `/reload`、RCON 触发、完成反馈和重建入口，不恢复已退役的 `##RD##` 日志提取器。
- **R4 查询集成**：同一服务器执行 `/mc_kb_dump` 后无需手工复制或补跑重建即可搜索；跨机部署仍可通过既有数据目录流程导入快照。复制 `commands.json` 仅迁移命令查询，不等于完整迁移物品知识库；完整物品迁移沿用现有流程，不在本期新增。
- **R5 统一数据契约**：输出包含 `name`、`syntax` 与 `producer`，并支持 `source`、`level` 等可选字段；契约供阶段二 RCON 生产者复用。RCON 快照的语法是 help 压缩形式（深层分支不完整），查询按 `producer` 显示降级说明；KubeJS 查询结果则说明已注册路径不等于当前调用者必然可执行。
- **R6 去重与兼容**：运行时条目与内置原版条目按明确规则去重；保留既有原版命令查询和合理的旧手工命令文件兼容。
- **R7 失败隔离**：命令类别失败不影响既有物品类别；无效或未完成的命令快照不得替换旧的有效发布缓存，回执需反映失败。
- **R8 版本兼容**：不破坏当前 1.19.2 的 runtime dump 能力，并对 1.20.1 的 dispatcher API 差异进行验证。

## Out of Scope

- RCON `help` 采集及其多包协议改造，由 `.trellis/tasks/10-25-rcon-help-command-fallback` 负责。
- 被动日志、JAR 静态扫描、新 Forge 导出 mod 和面板适配。
- 模组功能中文描述、语义搜索、精确 modid/权限/参数可选性、类型和范围推断。

## Acceptance Criteria

- [ ] **AC1 真实导出**：含 KubeJS 的模组服执行 `/mc_kb_dump` 后，产物包含服务端实际模组命令和至少一个多分支/带参数命令的完整 usage。
- [ ] **AC2 动态命令**：由 KubeJS 脚本注册的 `/researchdump` 自身可在快照与查询结果中找到，证明不是静态 JAR 清单。
- [ ] **AC3 查询闭环**：先临时移走数据目录中的旧 canonical 快照，首轮只执行一次 `/mc_kb_dump`，不手工补跑 `/mc_kb_rebuild`，即可通过 `search_mc_commands` 按根命令名及语法关键词查到条目；随后再执行一次 `/mc_kb_dump`，结果无重复。模拟跨机仅复制 `commands.json` 到数据目录后也能查询命令，但不宣称因此迁移了完整物品知识库。
- [ ] **AC4 原版、权限与去重**：无命令快照时原版清单及现有 `source/level` 显示照常工作；同一运行时命令覆盖或合并内置条目，不重复占用结果。运行时同根合并只继承 `desc/cat`，`level` 显示未知、`source=unknown`，不把原版默认权限或内置来源当作当前运行时验证结果。
- [ ] **AC5 既有能力不回退**：原 item/block/entity/fluid 导出、计数回执与物品知识库重建保持可用；命令导出失败有明确提示。
- [ ] **AC6 失败关闭**：损坏、截断或不符合 schema 的新命令文件不会成为有效快照，旧有效快照仍可查询。
- [ ] **AC7 测试与文档**：新建 `tests/`（标准库 unittest）覆盖 literal/argument、多分支、redirect、alias/去重、仅根 usage（`foo`）、根与子 usage 并存（`foo` / `foo bar`）、坏文件、运行时权限元数据、KubeJS 能力边界与 `producer=rcon` 降级显示；README 与 backend spec 更新命令产物、查询、跨机命令复制范围和限制说明。
