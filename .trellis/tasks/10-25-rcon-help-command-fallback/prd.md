# RCON help 模组命令回退采集

## Goal

为没有 KubeJS 的环境提供命令知识库生产者：通过独立管理员指令和现有 RCON 配置采集真实 `HelpCommand` 输出，并发布与已归档 KubeJS 子任务兼容的原子命令快照。

## Background and Dependency

- 父任务：`.trellis/tasks/10-25-mod-command-kb`。
- 代码依赖已完成：`.trellis/tasks/archive/2026-10/10-25-kubejs-command-dump/` 已建立命令 schema、缓存发布和查询集成；本任务只增加 RCON 生产者，不建立第二套消费链。
- 调研证实被动日志和 JAR 静态扫描不能提供可靠完整语法；RCON `help` 来自当前 dispatcher，是无 KubeJS 时的首选 fallback。
- **smart usage 降级口径**：vanilla `help <command>` 只调用 `getSmartUsage`，不是 `getAllUsage`。根级 `help` 给根命令 + 压缩子树；`help <root>` 给该根的一级子命令 usage，更深分支是 `(a|b)` / `[x]` 等压缩语法。本任务不声称与 KubeJS 主路径等价。
- 1.19.2/1.20.1 不采用 `/help <page>` 分页；目标根没有可见一级子命令时 RCON 收到合法空响应。空响应和根级单独 `/foo` 都不能证明裸根可执行。
- 当前 `aio-mc-rcon 3.5.0` 单包读取不能承载长 help；普通 `execute_async()` 语义保持不变。

## Start Gate

启动前必须完成（父任务 implement 阶段 4 的前置）：

- [x] `design.md`：锁定低层传输/API 落点、共享 `_send_lock`、A/B 状态机、smart usage 解析、纯根证据、预算、失败关闭和 `/mc_kb_rcon_scan`。
- [x] `implement.md`：P0 真机实测先于采集器实现，P1–P7 列明改动文件、验证命令与回滚点。
- [x] 在 CTI0.46（1.19.2）与 Farming（1.20.1）隔离副本完成多包、空包、A/B id 序列、禁止立即 A+B、共享锁和后续命令隔离实测，证据写入 `research/02-rcon-ab-probe.md`。
- [x] P0 已填真实资源值并确认 design 上限；实测值见 `implement.md` P0.3 与 `research/02-rcon-ab-probe.md`。P6、独立评审和后续开工许可仍未完成，不得仅因 P0 完成而启动产品实现。

## Requirements

- **R1 两阶段采集**：先通过根级 `help` 发现 RCON 可见根命令，再逐根获取一级子命令 usage，最后重做根 help 比较根集合；结果缓存，禁止在每次 `execute_command` 前全量扫描。根级压缩 smart usage 只作发现/结构证据，不冒充完整普通 usage。
- **R2 完整传输**：不得依赖 aiomcrcon 单包 `send_cmd()`。使用独立低层扫描 socket，但与现有 `_send_lock` 形成同一互斥边界；每次查询采用受控 A/B 状态机：收到 A 首包（合法空包也算）后才发送短随机未知 literal B，继续收 A，收到 B 完成。整次扫描内 request id 不复用；最后一次 B 后的有界尾随窗口内无包算该检查完成，不把静默误判为交换超时。禁止立即连写 A+B；EOF、截断、错/未知 id、B 缺失/尾随、超时和预算超限均关闭扫描 socket 并失败，不能污染后续普通命令。
- **R3 严格解析（smart usage）**：不假设反馈含换行；按 `/` 与已知根前缀切分并校验完整结构。解析 `(a|b)`、`[x]`、`-> target`、裸 `->`（仅作额外容错/合成夹具，允许尾部空白，归一为 `redirect="..."`）和 `...`：实测 redirect-to-root 是 `-> <target>`（如 `/execute as <targets> -> execute`），`...` 仅作 usage 尾部压缩占位；redirect 拆到共享 `redirect` 字段，其余压缩记号保留在 `syntax`。targeted 空响应合法且产生零条普通 entry；不得仅凭根级 `/foo` 或空响应发布普通 `syntax="foo"`。根级和 targeted 的显式 redirect 均可作为别名证据保留，KubeJS 有正向证据的纯根条目不受影响。异常、自定义或错误输出失败关闭，不依赖固定英文错误文本。
- **R4 原子发布**：仅当全部目标根采集、末次根集合检查、解析和共享校验成功后，才通过 `validate_snapshot()` + `publish_snapshot()` 替换有效快照；空 entries 不发布。中途失败保留旧缓存并报告阶段、失败根、进度和耗时。
- **R5 能力边界**：结果是权限等级 4 的 RCON source 当前可见命令；只保证一级子命令 usage 可还原，深分支保留压缩语法并标注 `producer=rcon`。纯根命令可能未收录，targeted 空响应不证明裸根不可执行；不保证包含被自定义 `requires` 隐藏或执行体要求玩家的命令，不伪造参数类型、权限或 modid。
- **R6 主路径协作与入口**：KubeJS 可用时仍优先结构化导出；只在无 KubeJS 环境由管理员显式执行 `/mc_kb_rcon_scan`。入口有权限检查、单飞、进度/失败根/耗时回执；不得被 `kb.enabled` 或本机 `mc_server_dir` 阻断跨机 RCON-only 查询。本机发现 KubeJS 正向证据时拒绝；跨机无法完整证明时，以独立管理员显式指令作为环境确认并说明限制。KubeJS 导出失败不自动 fallback。
- **R7 资源与一致性边界**：初始根 help + N 个 targeted + 末次根 help，连同每次 B 哨兵共 `2(N+2)=2N+4` 个 RCON 请求；必须有根数、片数、字节和总耗时上限。首尾根集合不一致或可发现结构异常时拒绝发布；同根集合下 dispatcher 热替换无法由 help 原子排除，不承诺全局原子快照。
- **P0 实测回填**：三组隔离副本均完成全量扫描，Farming N=182/368 请求，CTI-kubejs N=183/370 请求，CTI-nokubejs N=179/362 请求，均符合 `2N+4` 且首尾根集合一致；根 help 为 2–3 包、6892–10875 字符。完整数据与原始文件见 `research/02-rcon-ab-probe.md`，其中耗时仅为 targeted 交换循环耗时，不作为完整扫描预算或远程 SLA。
- **R8 可检测边界与运行前提**：扫描期间不得有其他 RCON 客户端写入命令，包括服务器面板或其他管理员的独立连接；本插件 `_send_lock` 只约束自身，正常多包完整性保证只在此前提、逐请求顺序、TCP 有序性和 B 哨兵下成立，不能声称外部并发安全。管理员回执和 README 必须提示该前提；P0 已实测同 ID 双份完整响应，双客户端竞争只记录故障形态，一次未复现不等于证明安全。idle-drain 只能诊断。RCON 无片序号/总长度，不承诺检测“中间内容片删除但仍收到合法 B”等任意内容删除。

## Out of Scope

- `/help <page>` 分页循环、被动日志推断、JAR 静态扫描。
- 把 smart usage 展开成 `getAllUsage` 等价完整路径的展开器。
- 通用服务器面板/控制台连接器和新 Forge 导出 mod。
- 将 RCON help 提升为替代 KubeJS 的首选主路径，或从 KubeJS 导出失败自动启动全量扫描。
- 玩家限定命令的执行适配、语义描述和精确权限/modid/参数类型推断。
- 承诺排除同根集 reload、任意中间删片或所有理论上不可观察的故障。

## Acceptance Criteria

- [ ] **AC1 无 KubeJS 闭环**：在移除 KubeJS 及必需附属 mod 的隔离副本，仅配置 RCON 完成 `/mc_kb_rcon_scan` 后，`search_mc_commands` 能返回模组根及一级子命令 usage；Farming 的浅树 `wine age <years>` / `wine info` 完整还原，CTI 用该副本实际存在的浅树命令验收；无一级子命令/redirect 证据的纯根可不出现在 RCON 快照中，不以根级 `/foo` 或空 targeted 补造。跨机场景不被 `kb.enabled` 或本机 `mc_server_dir` 阻断。
- [ ] **AC2 传输完整**：在没有其他 RCON 写入者的前提下，超过 4096 字符的多包响应按 A/B request id 完整接收；B 缺失/错 id 等可观察故障失败关闭，后续普通 RCON 命令收到自己的响应而非遗留 help 分片。最后一次 B 后的尾随窗口静默到期算检查完成，窗口内收到尾随包才失败；idle-drain 不作为通过依据。
- [ ] **AC3 解析正确**：无换行、多分支、redirect、深层 `(a|b)` 压缩和空 targeted 夹具得到预期结构；根级 `/foo`、root-only、`foo` 与 `foo bar` 并存夹具证明 RCON 不伪造普通纯根，真实 `-> target`（含 root target 的名字形式）正确拆分；裸 `->`（含尾部空白）仅作为额外容错/合成夹具归一为 `redirect="..."`，不得冒充本次实测形态，KubeJS 纯根保持不变。查询显示 `producer=rcon` 的深分支和“纯根可能未收录”说明。
- [ ] **AC4 失败关闭**：EOF、截断 length/body、错/未知 id、B 缺失、B 后窗口内尾随包、交换/总超时、片数/字节超限、本地化错误、自定义异常 help、首尾根集合不一致及跨交换旧 id 迟到等场景不产生部分快照，旧缓存仍可查且后续命令不受污染；合法空 targeted 和最后 B 后尾随窗口静默不触发失败。首尾根集合变化优先用确定性 fake-server 验收；任意中间内容片删除、同根集热替换和外部 RCON 并发写入按 R8/R7 的不可保证边界记录，不虚构通过证据。
- [ ] **AC5 能力检测与管理入口**：非标准 `help` 或无法确认结构/完整性时给出明确回执，不把错误文案写入知识库；`help help`、`help 1` 和不存在命令只作探针，不实现分页。非管理员零 RCON、重复调用不排队、KubeJS 环境拒绝、失败根/进度/耗时回执均有入口级测试或可重复人工记录；至少一条经生产 `/mc_kb_rcon_scan` 入口验证，而非只运行底层探针。
- [ ] **AC6 分环境差分与性能**：AC1 在无 KubeJS 副本验收；AC6 在 CTI0.46（1.19.2）与 Farming（1.20.1）的有 KubeJS 隔离副本，对同一 dispatcher 做结构化导出与 RCON 探针对照，比较发现根集合和一级子命令集合，记录深层压缩、纯根缺失、权限差异、实际 `2N+4` 请求数及耗时。技术对照不开放 KubeJS 环境下的生产 fallback 入口。
- [ ] **AC7 文档**：说明 `/mc_kb_rcon_scan`、管理员环境确认、扫描期间暂停其他 RCON 写入者、RCON 可见性、深分支与纯根降级、缓存优先级、失败处理、请求预算、尾随窗口语义、卸载取消和跨机使用方式。

## Research

- `research/01-command-enumeration.md`：无 KubeJS 方案比较、对应版本源码证据、RCON 风险与最小实测清单。
- `research/02-rcon-ab-probe.md`：已产生的双版本 A/B、全量 `2N+4`、锁/隔离、并发和环境实测；原始 `p0-*.json` 保留，字段限制与修正解释见该报告。
- P0 另实测现有 `execute_async("help")` 截断 4096 字符并污染后续 `list`，因此长响应扫描必须独立低层 socket 且失败关连接；双客户端同 ID 重复响应的机制未定位，不得宣称 ID 匹配提供并发安全。
- `research/03-live-acceptance.md`：P6 完成后产生的双副本 AC 验收证据；当前尚不存在，未完成前不得归档。
