# RCON help 模组命令回退采集

## Goal

为没有 KubeJS 的环境提供命令知识库生产者：通过现有 RCON 通道采集真实 `HelpCommand` 输出，并发布与阶段一兼容的原子命令快照。

## Background and Dependency

- 父任务：`.trellis/tasks/10-25-mod-command-kb`。
- 实施顺序依赖 `.trellis/tasks/10-25-kubejs-command-dump`：先复用其命令 schema、缓存发布和查询集成，再增加 RCON 生产者。
- 调研证实被动日志和 JAR 静态扫描不能提供可靠完整语法；RCON `help` 来自当前 dispatcher，是首选 fallback。
- **2026-10-25 复核修订（降级口径）**：vanilla `help <command>` 只调用 `getSmartUsage`，不是 `getAllUsage`。根级 `help` 给根命令 + 压缩子树；`help <root>` 给该根的**一级子命令** usage（浅树可完整还原），更深分支是 `(a|b)` / `[x]` 压缩语法。本任务不声称与 KubeJS 主路径等价。证据见 `research/01-command-enumeration.md` 同名小节。
- 1.19.2/1.20.1 不采用 `/help <page>` 分页；目标根没有可见一级子命令 usage 时 RCON 收到空响应，属于合法结果，且不得删除根级 `help` 已采集的该根条目。
- 当前 `aio-mc-rcon 3.5.0` 单包读取不能直接承载长 help 响应。

## Start Gate

启动前必须补齐（父任务 implement 阶段 4 的前置）：

- [ ] `design.md`：传输层落点（扩展 `rcon_client.py` 还是新增低层客户端、如何不影响现有 12 个 LLM 工具与普通命令语义）、smart usage 解析与归一、根级与 targeted usage 的合并/去重规则、空响应保留根级条目与失败关闭判定、管理员触发入口。
- [ ] `implement.md`：多包接收与结束判定的真机实测先于采集器实现；按步列验证命令与回滚点。
- [ ] 调研中的多包/结束判定、`help` 输出形态和空响应行为在获批实例上实测确认。

## Requirements

- **R1 两阶段采集**：先通过根级 `help` 发现 RCON 可见根命令并保留根级 smart usage 作为采集输入，再逐根获取**一级子命令** usage；缓存结果，禁止在每次 `execute_command` 前全量扫描。
- **R2 完整传输**：按 request id 接收全部响应分片，具备有界结束判定、超时和清理/重连策略；不得读取一片即返回或让残片污染后续命令。
- **R3 严格解析（smart usage）**：不假设 RCON 反馈含换行；利用 `/` 分隔与已知根前缀切分，解析 smart usage 记号（`(a|b)`、`[x]`、`-> target`、`...`）：redirect 记号按共享契约拆到 `redirect` 字段，其余压缩记号保留在 `syntax`。空响应表示该根没有可见一级子命令 usage，属合法结果，不按失败处理，且必须保留根级 `help` 中该根的已有条目；根级与 targeted 结果的合并/去重规则由后续 design 固定，合法 `syntax == name` 不得过滤。遇到非预期、自定义或错误输出时放弃本次快照，不依赖固定英文错误文本。
- **R4 原子发布**：仅当全部目标命令采集与校验成功后替换有效快照；中途失败保留旧缓存并报告失败根、耗时等可诊断信息。
- **R5 能力边界**：结果是权限等级 4 的 RCON source 当前可见命令；语法是 HelpCommand smart usage 的降级形式——根命令与一级子命令可还原，更深分支保留压缩语法并由查询层标注 `producer=rcon`；不保证包含被自定义 `requires` 隐藏或执行体要求玩家的命令，也不伪造参数类型/权限/modid。
- **R6 主路径协作**：KubeJS 可用时仍优先结构化导出；fallback 只在无 KubeJS 环境由管理员显式触发，成功后使用共享发布契约替换快照，任何失败均保留旧缓存；不在 KubeJS 导出失败时自动启动 N+1 扫描。
- **R7 资源限制**：全量 N+1 采集必须有请求数、响应大小和总耗时的合理边界；扫描期间 reload 或数据不一致时不得发布混合快照。

## Out of Scope

- `/help <page>` 分页循环、被动日志推断、JAR 静态扫描。
- 把 smart usage 展开成 `getAllUsage` 等价完整路径的展开器（本期明确不做；深层分支按压缩语法呈现并标注）。
- 通用服务器面板/控制台连接器和新 Forge 导出 mod。
- 在本期将 RCON help 提升为替代 KubeJS 的首选主路径。
- 玩家限定命令的执行适配、语义描述和精确权限/modid 推断。

## Acceptance Criteria

- [ ] **AC1 无 KubeJS 闭环**：仅配置 RCON 的目标服完成采集后，`search_mc_commands` 能返回模组根命令及**一级子命令** usage；浅树命令（如 `wine age <years>` / `wine info`）必须完整还原。
- [ ] **AC2 传输完整**：超过 4096 字符的多包响应被完整接收并按 request id 隔离；后续普通 RCON 命令收到自己的响应而非遗留 help 分片。
- [ ] **AC3 解析正确**：无换行、多分支、redirect、深层 `(a|b)` 压缩夹具得到预期结构化结果；另覆盖仅根 usage（root-only）、根与子 usage 并存（`foo` / `foo bar`）及 targeted 空响应（empty-targeted），验证合并/去重且空响应不删除根级条目。根级 smart usage 不被当成完整结果；查询侧显示 `producer=rcon` 的语法降级说明。
- [ ] **AC4 失败关闭**：缺包、错 id、超时、本地化错误、自定义 help、中途 reload 等场景不产生部分快照，旧缓存仍可查；空响应不触发失败关闭。
- [ ] **AC5 能力检测**：非标准 `help` 或无法确认完整性时给出明确回执，不把错误文案写入知识库。
- [ ] **AC6 差分与性能**：在已获批的 CTI0.46（1.19.2）与 Farming（1.20.1）上与同一 dispatcher 的结构化导出比较**根集合与一级子命令集合**，记录深层压缩差异原因、请求数及耗时。
- [ ] **AC7 文档**：说明 fallback 触发方式、RCON 可见性限制、**语法降级边界**、缓存优先级、失败处理和跨机使用方式。

## Research

- `research/01-command-enumeration.md`：无 KubeJS 方案比较、对应版本源码证据、RCON 风险与最小实测清单；含 2026-10-25 的 `help` / `getSmartUsage` 复核修订。
- RCON 多包结束哨兵/等价组包方式及自定义 help 探针仍需在获批测试实例上实测；这是阶段二启动前的技术验证，不改变已确认的产品范围。
