# 模组命令知识库运行时导入

## Goal

让 LLM 在调用 `execute_command` 前，能够通过现有 `search_mc_commands` 查询服务端当前 dispatcher 已注册的模组命令及 usage 路径，并能将中文用户意图提炼为英文概念词后召回候选；优先使用 KubeJS 结构化导出，无 KubeJS 时使用 RCON `help` 回退采集。已注册路径不代表当前调用者必然可执行。

## Confirmed Decisions

- 用户最初选择语法级 MVP：真实命令名与参数 usage，不做语义级模组功能文档；2026-10-26 根据实际使用反馈，新增独立的英文意图检索改进，仍不建设自动中文描述或语义映射库。
- KubeJS 保留主路径；无 KubeJS 的 RCON help fallback 纳入本次总需求。
- 交付采用一个父任务和三个子任务；先完成共享契约/KubeJS，再分别实施 RCON fallback 与英文意图检索改进，后两者均只依赖子任务一。
- `getAllUsage` 不能提供参数可选性、类型或范围，这些不属于验收承诺。
- CTI0.46 与 Farming 均获本任务部署、reload、启动实测授权；Farming 是已不用的旧服务器。
- 评审决定（2026-10-25）：RCON fallback 采用降级口径——只承诺根命令与一级子命令 usage，更深分支保留 help 压缩语法并在查询侧标注，不声称与 `getAllUsage` 等价。
- 规划复核（2026-10-26）：RCON 不凭根级 `/foo` 或空 targeted 伪造普通纯根；长响应采用 A 首包后 B 的受控状态机，请求预算为 `2N+4`。同根集热替换和任意中间删片不属于可保证检测范围。
- 评审决定（2026-10-25）：离线回归新建 `tests/`（标准库 unittest）；遵循 AstrBot 根项目的 ruff 配置，只对新增/改动文件运行 ruff format/check，不做全仓 reformat，不引入 pytest 或新运行时依赖。

## Background and Confirmed Decisions

- 来源 Issue：`fanjinchi/astrbot_plugin_mc_manager#5`。
- 当前已有原版命令清单 `assets/vanilla_commands.json`、查询工具 `main.py:635` 和执行前查询引导 `main.py:569`；`kb/commands.py:50` 仅预留模组命令文件读取入口，尚无生产者。
- 生产者保持**语法级 MVP**：保证命令名与参数语法；后续检索增强只利用英文 usage 和调用方 LLM 的跨语言能力，不建设中文功能描述或语义映射库。
- 模组来源无法可靠判定时允许 `source="unknown"`；权限等级无法可靠取得时允许 `level=null`。两者均不阻塞核心导出。
- KubeJS 是主路径；RCON `help` 是无 KubeJS 时的首选 fallback。被动日志推断和 JAR 静态扫描不进入生产方案。
- 父任务按三个子任务交付；RCON fallback 与英文意图检索均复用子任务一确定的数据契约与查询集成，不在子任务一完成前开始实现。

## Requirements

- **R1 真实运行时数据**：命令条目必须来自服务端当前 Brigadier `CommandDispatcher` 或其 `HelpCommand` 输出，不从 mod 列表猜测。
- **R2 运行时 usage**：KubeJS 主路径至少提供根命令名和当前 dispatcher 已注册的完整 usage 路径；这不代表当前 RCON/玩家必然可执行，实际执行仍受 `requires`、source 类型和执行体内部玩家检查限制。RCON fallback 只承诺有正向证据的一级子命令 usage/redirect，更深分支是 help 压缩语法，纯根命令可能未收录，必须标注、不声称完整。
- **R3 KubeJS 主路径**：扩展现有 runtime dump 和 `/mc_kb_dump`，保持现有物品 dump 能力，并接入命令查询。
- **R4 RCON fallback**：无 KubeJS 时，通过根级 `help` 发现命令，逐根 `help <command>` 获取一级子命令 usage，末次根 help 检查根集合（HelpCommand 只提供 getSmartUsage）；包含共享 `_send_lock`、A 首包后 B 的完整多包接收、smart usage 严格解析、显式 redirect、空 targeted 不回填纯根和原子缓存发布。
- **R5 统一只读查询**：两条生产路径复用 `search_mc_commands`，保留无 dump 时的原版命令查询，并避免内置与运行时条目重复。
- **R6 失败关闭**：解析、传输或导出失败时不得发布截断/部分快照；旧的有效命令缓存仍可查询。RCON 采集不得让残留响应污染后续命令。
- **R7 派生缓存**：命令数据可重建、可随服务器目录或跨机拷贝流程更新，不作为手工维护的权威配置。跨机复制 `commands.json` 仅承诺迁移命令查询，不等于完整迁移物品知识库；完整物品迁移沿用既有流程，不在本期新增。
- **R8 兼容与边界**：保持项目支持的 Python 3.10+、Minecraft 1.19.2 和 1.20.1 目标；只承诺 RCON source 可见的 fallback 命令，不保证绕过执行体内部的玩家限制。
- **R9 中文意图下的英文检索**：调用方 LLM 先将中文意图提炼为英文概念词；查询支持无序 token AND 和空格/`_`/`-` 兼容，保留原版中文 desc 搜索，不承诺模组中文直搜，不引入自动翻译、同义词库或语义层。具体验收由 `.trellis/tasks/archive/2026-10/10-26-command-intent-search` 承担。

## Task Map and Ordering

| 顺序 | 子任务 | 独立交付物 |
|---|---|---|
| 1 | `.trellis/tasks/archive/2026-10/10-25-kubejs-command-dump` | KubeJS 命令树结构化导出、命令缓存发布、`search_mc_commands` 接入及主路径文档 |
| 子任务一后 | `.trellis/tasks/10-25-rcon-help-command-fallback` | 无 KubeJS 的 RCON help 采集、完整传输与解析、失败保护及 fallback 文档 |
| 子任务一后 | `.trellis/tasks/archive/2026-10/10-26-command-intent-search`（✅ 2026-10-28 完成并归档） | 英文调用引导、无序 token AND 匹配、离线回归及真实 AstrBot 模型 5/5 召回验证 |

## Out of Scope

- 中文命令功能描述、自然语言语义映射或翻译库。
- 被动解析 `logs/latest.log` 还原命令树。
- JAR 字节码扫描器及将静态候选直接作为可靠命令数据。
- 新 Forge 导出 mod、通用面板/控制台连接器；仅当 RCON 路线实测不可行时重新评审。
- 准确推断所有命令的 modid、整数权限、参数可选性、参数类型和数值范围。
- 每次 `execute_command` 前执行全量 RCON 扫描。
- 将 RCON fallback 在本期直接提升为取代 KubeJS 的主路径。

## Acceptance Criteria

- [ ] **AC1 主路径**：在含 KubeJS 和模组命令的服务器执行 `/mc_kb_dump` 后，`search_mc_commands` 能返回实际模组命令及当前 dispatcher 已注册的完整 usage 路径，且既有物品 dump/重建结果不回退；结果不得暗示当前调用者必然可执行。
- [ ] **AC2 无 KubeJS fallback**：在移除 KubeJS 及必需附属 mod 的隔离副本，仅通过 RCON 完成 `/mc_kb_rcon_scan` 后，可查询 RCON 可见的模组根及一级子命令 usage（浅树如 `wine age <years>` / `wine info` 完整还原）；深层压缩和纯根可能未收录以 `producer=rcon` 标注，不冒充完整参数。
- [ ] **AC3 原版兜底**：没有 KubeJS、dump 文件或 RCON 快照时，内置原版命令仍可搜索；运行时与内置条目不产生重复结果。
- [ ] **AC4 元数据边界**：查询结果允许缺省 `source`/`level`，但 `name` 必定可用；纯内置 vanilla 条目保留现有来源/权限显示，运行时同根合并只继承内置 `desc/cat`，`level` 按未知处理、`source=unknown`，不推断当前运行时 mod 归属。KubeJS 快照的 `syntax` 是当前 dispatcher 已注册的完整 usage 路径，实际执行仍受权限和 source 限制；RCON 快照的 `syntax` 可能是 help 压缩语法且必须标注，不把未知信息伪造为确定值。
- [ ] **AC5 失败安全**：EOF、截断 length/body、错/未知 request id、B 缺失/尾随、超时、片数/字节超限、非预期 help 输出、首尾根集合不一致或单个类别导出失败时，不发布部分快照、不覆盖旧有效缓存、不污染后续 RCON 响应；不承诺检测任意中间删片或同根集热替换。
- [ ] **AC6 验证与文档**：离线测试覆盖多分支、redirect、多包、无换行、root-only/根与子 usage 并存、empty-targeted 和本地化/异常输出，证明 RCON 不伪造普通纯根而 KubeJS 纯根不变；README 与相关 Trellis spec 同步说明两条采集路径、A/B 与一致性边界和跨机命令数据流程（不扩张为完整物品迁移）。
- [ ] **AC7 中文意图检索**：实际 AstrBot 模型对子任务三规定的 5 条中文意图均通过英文概念词召回正确根与目标 usage；原版中文 desc 搜索保持可用，未通过时不以自动中文生成或语义层自行扩 scope。

## Technical Research

- RCON 方案调研保存在 `.trellis/tasks/10-25-rcon-help-command-fallback/research/01-command-enumeration.md`；该调研于 2026-10-25 确认 `help` 只提供 smart usage，并于 2026-10-26 补充纯根证据、A/B 状态机、`2N+4` 预算和可检测一致性边界。
- KubeJS dispatcher 访问方式、统一命令 schema 和缓存发布位置属于阶段一设计事项，不改变上述产品范围。
