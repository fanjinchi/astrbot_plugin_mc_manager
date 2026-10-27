# RCON help 回退采集技术设计

> 状态：P0 真机探针已完成，证据已写入 `research/02-rcon-ab-probe.md`；本任务仍保持 `planning`，P6 验收、回填后的独立评审和后续开工许可未完成前，不得进入产品实现。
>
> 本设计只使用现有共享命令快照，不改变 schema，不新增配置项或第三方依赖。

## 1. 已锁定的边界

- 独立管理员指令 `/mc_kb_rcon_scan` 显式触发；KubeJS 导出失败时不自动 fallback，不在查询或 `execute_command` 前扫描。
- 复用已归档子任务一的 `validate_snapshot()` / `publish_snapshot()` 与 `search_mc_commands` 消费链，权威产物仍为 `<plugin_data>/runtime_dump/commands.json`，`producer="rcon"`。
- 只发布 RCON source 可见的、有一级子命令或显式 redirect 正向证据的 usage。根级 `help` 的压缩子树和 targeted 空响应均不能证明裸根可执行；不得仅凭 help 生成普通 `syntax == name` 条目。纯根命令可能完全不出现在 RCON 快照中，查询必须说明这一点。
- KubeJS 对纯根有 `getAllUsage` 正向证据，现有 `syntax == name` 条目和共享 schema 保持不变；不能为了 RCON 限制而全局过滤纯根条目。
- RCON 无分片序号或总长度。A/B 状态机可验证本文列出的传输故障，但不承诺识别“伪造服务端删除中间内容片后仍发送合法 B”等任意内容删除；首尾根集合检查也不等于 dispatcher 全局原子快照。

## 2. 当前代码事实与最小落点

### 2.1 不得改变的现有行为

- `rcon_client.py` 的 `execute_async(command: str, timeout: float | None = None) -> str` 签名、aiomcrcon 默认 2 秒语义、连接异常重试、超时重连但不重发、成功空反馈文案和 `错误:` 返回约定全部不变。
- 现有普通命令、12 个 LLM 工具、`test_connection_async()`、`RuntimeDumpRunner` 仍走 `execute_async()`；长 help 不得调用 aiomcrcon 单包 `send_cmd()`。
- `kb/commands.py` 的共享 schema 继续允许 KubeJS 纯根；`publish_snapshot()` 仍负责完整校验、同目录临时文件和 `os.replace()`。失败时不写临时权威文件、不删除旧快照。
- `kb/__init__.py` 当前即使 `kb.enabled == False` 也会以 `StarTools.get_data_dir()` 初始化 `self.data_dir`；`search_mc_commands` 不检查 `kb.enabled`。因此跨机 RCON-only 查询可继续使用 `self.kb.data_dir`，无需也不得依赖本机 `mc_server_dir`。

### 2.2 文件/API 落点

| 文件 | 最小改动 | 责任 |
|---|---|---|
| `rcon_help.py`（新增） | stdlib-only 低层客户端、A/B 交换、两阶段编排和纯函数解析 | 不 import AstrBot，不接触发布目录，不调用现有普通 RCON socket |
| `rcon_client.py` | 新增 `scan_help_commands(...) -> tuple[dict \| None, dict]` | 在同一个 `_send_lock` 内调用采集器，统一返回快照/诊断报告 |
| `main.py` | 新增 `/mc_kb_rcon_scan`、`_rcon_scan_lock` 和活动扫描任务归属；接入 `terminate()` | 权限、环境门槛、单飞、进度回执、调用共享校验/发布，以及卸载时有界取消和清理 |
| `kb/commands.py` | 扩充 RCON producer 提示 | 明确深分支压缩及“纯根命令可能未收录”，不改 schema |
| `tests/test_rcon_help.py`（新增） | fake server、解析、编排和锁回归 | 标准库 `unittest` |
| `tests/test_commands.py` | 更新 RCON 提示断言 | 保留 KubeJS 和 vanilla 回归 |

`runtime_dump.py`、`kb/__init__.py` 和共享快照字段预计不需要改动；若实施发现必须改动，先回到本设计和父任务评审，不顺带重构。

`scan_help_commands()` 的返回约定：

- 成功：`(snapshot, report)`；`snapshot` 含 `kind/schema_version/producer/count/entries`，尚未写盘。
- 失败：`(None, report)`；`report` 至少含 `phase`、当前/失败 `root`、`completed_roots`、`root_count`、`requests`、`packets`、`bytes`、`elapsed_ms` 和中文 `reason`。
- 可预期传输/解析失败不得穿透 AstrBot 事件管线；意外异常在现有主指令边界记录日志并返回失败回执。扫描不自动重试，管理员只能显式重新执行整次扫描。

`rcon_help.py` 内部可用一个小型不可变 limits dataclass 约束预算，避免在多个函数复制参数；不新增配置表面。复杂协议/解析函数必须写 Google-style docstring，公开函数保留完整类型标注。

## 3. 互斥、socket 生命周期与单飞

### 3.1 同一互斥边界

服务端不同 RCON socket 共享 `RconConsoleSource` 反馈缓冲，独立 socket **不是**天然隔离。生产扫描只能经 `MinecraftRCON.scan_help_commands()` 进入：

1. 获取现有 `self._send_lock`。
2. 在锁内创建独立扫描 socket，完成认证、首末根 help、全部 targeted 交换及最后的结构检查。
3. 在 `finally` 中关闭扫描 writer 并等待关闭，再释放 `_send_lock`。
4. 文件校验/发布在主指令中进行；单飞锁仍持有，但不为了磁盘 IO 扩大 RCON `_send_lock` 粒度。

锁覆盖**整次扫描**，而不是每个 help 请求分别获取。这样普通 `execute_async()`、`/test_connection`、runtime dump 等即使另用现有客户端 socket，也只能等待，不会在 A/B 之间写入并污染共享反馈缓冲。现有 `_ensure_connection()` 可在等待发送锁前建立连接，但在锁释放前不得发送数据，不需要改其结构。

`_rcon_scan_lock` 只负责管理入口单飞：第二个 `/mc_kb_rcon_scan` 立即收到“已有扫描进行中”，不排队发起第二轮 N+2 个 help。它与 `_dump_lock` 职责不同；真正防止 dump/scan RCON 串包的是共同 `_send_lock`。

**扫描运行前提**：扫描期间必须暂停其他 RCON 客户端的命令写入，包括服务器面板和其他管理员的独立连接。`_send_lock` 只能约束本插件，不能约束外部客户端；因此上述互斥和 A/B 完整性保证只在该前提下成立。无法满足时不得把扫描结果称为完整；P0 可用双客户端竞争记录故障形态，但一次未复现不证明并发安全，本期不新增外部面板锁。

### 3.2 清理与后续命令隔离

- 扫描 socket 每个任务只使用一条；成功、失败、取消、超时均关闭，不复用 aiomcrcon 的 `_client`。
- 扫描失败后只丢弃扫描 socket，不重连/重发普通客户端命令，也不清空或篡改现有客户端状态。
- `_send_lock` 在 socket 关闭后释放；下一条普通命令必须得到自己的响应。残片只能随扫描 socket 被丢弃，不能进入下一条命令。
- 所有读写使用有界 `asyncio` 等待；收到 EOF、长度/正文截断或预算超限立即失败关闭，不做 idle-drain 补偿读取。
- 活动扫描任务由当前插件实例持有；`terminate()` 先取消该任务并有界等待其清理，扫描的 `finally` 必须关闭 writer 并等待关闭完成，之后卸载才返回。重载/禁用期间不得让旧实例继续写 RCON；入口级取消/重载验收必须覆盖这一生命周期，而不只测试函数内部收到 `CancelledError`。

## 4. 受控 A/B 请求状态机

### 4.1 请求定义

每个逻辑查询都是一次 A/B 交换：

- A 为 `help`、`help <root>`，或 P0 专用能力探针。
- B 为短随机、无副作用且不可能正常注册的未知 literal，例如带一次扫描随机后缀的保留前缀；不得使用真实命令、带参数命令或固定英文反馈判断。
- A、B 使用不同的合法 request id；整次扫描内所有 request id 均不复用，同次交换只接受当前预期 id。这样迟到的旧包不会恰好变成后续交换的合法响应。B 的本地化未知命令文本只用于完成信号，不进入解析或知识库。

### 4.2 状态转换

```text
AUTH_OK
  -> SEND_A
  -> WAIT_A_FIRST          # 此时绝不能发送 B
  -> SEND_B                # 仅收到 id=A 的首包后；空 body 也是合法首包
  -> WAIT_A_OR_B           # id=A 继续拼接，id=B 完成
  -> CHECK_TRAILING        # 仅最后一次 B；其他交换直接进入下一 SEND_A
  -> EXCHANGE_DONE
```

具体规则：

1. 发送 A 后，先读完整 length/id/type/body 框架；在收到 A 首包之前，B 尚未写入。
2. 首包必须为当前 A id。空响应也必须由真实 `id=A` 空包表示，不能把“读不到数据”当作空响应。
3. 只有首包合法后才发送 B。禁止 `write(A); write(B)` 连写：目标服务端 `BufferedInputStream.read(..., 1460)` 可能合并读取并按 framing 错误断连。P0 已在隔离副本执行该负面试验；本次实际未断连、未见错 ID，但不改变禁止连写和不得依赖该行为的规定。
4. B 发送后，继续收集所有 `id=A` 包；收到 `id=B` 即确认 A 的响应发送序列已结束，忽略 B 文本。
5. 非最后一次交换收到 B 后直接进入下一交换；交换间或下一阶段收到额外、旧或未知 id 均失败。最后一次交换开始前从整次扫描总预算中预留独立的 `trailing_window`（毫秒值由 P0 校准），预留不足则在发送最后 A 前失败；最后 B 后进入 `CHECK_TRAILING`。窗口内收到任何额外包失败；窗口内无包则该检查成功完成，静默到期不是交换超时。该窗口只用于最后 B 后，单次 A/B 交换超时只覆盖 SEND_A 到收到 B，不能把每次交换机械等待 10 秒；总预算包含这段预留窗口，B 之前已经发生的交换/总超时仍失败。最终窗口结束及 socket 关闭后的包不可观察，不能夸大为绝对完整性保证。
6. 正常完整性依据是：没有其他 RCON 写入者、服务端逐请求执行/发送顺序、TCP 有序性、A 首包后才发 B、以及 B 到达；不能用“若干毫秒没有新包”替代 B。

### 4.3 失败关闭清单

以下任一情况使整次扫描失败，关闭扫描 socket，返回 `(None, report)`，保留旧快照：

- 认证失败、EOF、连接重置；
- length 字段非法或截断、body/终止字节截断、UTF-8/框架结构非法；
- A 首包前收到错 id，或任何阶段收到错/未知 id；
- A 首包未到、B 缺失、交换超时或总超时；
- B 后观察到窗口内尾随包，或交换间/下一阶段收到旧 id；
- 单响应/总片数或字节预算超限；
- 根集合首尾不一致、help 输出结构异常、目标根解析失败；
- 任一 targeted 失败，或最终 entries 为空/共享校验失败。

`CHECK_TRAILING` 的静默到期不在失败清单内：它表示这项有界检查正常完成，不是 A/B 交换超时。RCON 协议没有片序号和总长度，因此“中间内容片被删除但仍收到合法 B”不能被普遍检测；外部 RCON 写入者也不在本插件可保证的检测范围内。AC2/AC4 只验证上述可构造、可观察故障，不写“所有缺包均可检测”的绝对承诺。

## 5. 两阶段采集与一致性

设初始根 help 严格解析得到 `N` 个不同根：

1. **首次根 help**：执行 A=`help` 的 A/B 交换。根响应必须非空、结构合法并包含 vanilla `help` 根，否则报告不支持/非标准 help。根行用于发现根集合和显式根 redirect，不作为完整普通 usage 发布。
2. **N 次 targeted**：按稳定排序逐根执行 A=`help <root>`。每个响应都独立完整接收和解析；任一失败立即终止，不继续发布部分结果。
3. **末次根 help**：再次执行 A=`help`，严格解析并比较根集合。集合不一致则拒绝发布；顺序变化但集合相同不算变化。末次输出也必须是合法根 help 结构。
4. **汇总**：只从有正向证据的 targeted usage 和显式 redirect 生成 entries，按共享规则去重/稳定排序，构造 `producer="rcon"` 快照。
5. **发布**：全部交换、末次检查和解析成功后，主指令才调用 `validate_snapshot()` 与 `publish_snapshot()`；空 entries 不发布。共享发布函数原子替换 `<data_dir>/runtime_dump/commands.json`。

首尾比较只能发现根集合增删及可发现的结构异常。它**不能**排除同根集合下 `/reload` 替换了一级/深层结构，也不能阻止游戏控制台、其他管理端在扫描期间修改 dispatcher；因此不承诺全局原子或同时刻快照。检测不到同根热替换属于明示残余限制，不通过额外时间戳或猜测伪造保证。

## 6. smart usage 严格解析与归一

### 6.1 分隔与能力校验

- 不调用 `splitlines()` 依赖换行。响应若为空，仅 targeted 可接受；根 help 为空按能力/结构失败。
- 非空响应必须从 `/` 开始；按 `/` 候选行切分后逐行验证，不能搜索到一段像 usage 的文本就忽略其余错误文本。
- targeted 每行必须匹配当前已知根前缀：`/<root> <非空 smart usage>`，或符合显式 redirect 结构。其它根、缺少根、裸错误文本、多余非空片段都使该根失败。
- 根 help 的每行提取根 literal 并检查结构、重复和根名合法性；用于 targeted 的根来自首次根集合，末次不得悄悄引入新根。
- 不依赖 `Unknown command` 等固定英文。A 的本地化错误/自定义非预期文本因不满足完整结构而失败；B 的文本不参与判断。

### 6.2 普通 usage、压缩记号与 redirect

- 普通 targeted 行去掉前导 `/` 后保存为 `syntax`，其中 `(a|b)`、`[x]`、`...` 等压缩记号原样保留，不展开成 `getAllUsage`。
- `-> target` 按共享契约拆为 `redirect="target"`；P0 实测 root target 也是名字形式，例如 `/execute as <targets> -> execute` 的 target 为 `execute`。`...` 只作为 usage 尾部压缩占位，不是本次实测的 root redirect 形态。根级或 targeted 的裸 `->`（允许尾部空白）仅作为额外容错/合成夹具归一为 `redirect="..."`，不得冒充真实输出。redirect 仅作别名提示，不渲染成已证明可执行的普通路径。
- targeted 空响应表示没有可见一级子命令 usage，产生零条普通 entry；它不是传输失败，也**不回填**根级 `/foo` 为 `syntax="foo"`。
- 根级单独 `/foo`、根级压缩 `/foo (a|b)` 均不证明裸 `foo` 有 `executes`。RCON 普通 entry 必须至少有根之后的一级 usage 证据。
- 只有显式 redirect 是例外：例如 `/alias -> target` 可保留 `syntax="alias", redirect="target"`；实测 `/xp -> experience`、`/execute as <targets> -> execute` 也按目标名字保留。`/alias ->`（含尾部空白）只能作为额外容错/合成夹具保留 `syntax="alias", redirect="..."`，因为证据表达的是别名而非裸根可执行。根级和 targeted 两组夹具都必须覆盖真实 `-> target`，另覆盖合成裸 `->`；根 redirect 的 targeted 空响应不删除这条正向 redirect 证据。
- 非 redirect 的裸 targeted `/foo` 属于本设计没有预期的自定义/异常输出，失败关闭而不是猜测成纯根；KubeJS 已有纯根校验和测试不受影响。
- 所有 entry 使用 `source="unknown"`、`level=null`，不推断 modid、权限、参数类型、范围、可选性或玩家限制。
- 若所有根都没有可发布 usage/redirect，最终 entries 为空，共享校验拒绝发布并保留旧快照；不能为了“有结果”回填纯根。

## 7. 请求与资源预算

每次 A/B 交换包含一个 A 请求和一个 B 请求。采用首末根集合检查时：

- help 请求数：`1 + N + 1 = N + 2`；
- B 哨兵请求数：`N + 2`；
- **总 RCON 请求数：`2(N + 2) = 2N + 4`**，不是旧的 N+1，也不是漏掉末次根检查的 `2(N+1)`。

以下是 P0 实测值与实现初始硬上限的对照。实测来自隔离副本回环，不是远程 SLA；硬上限仍是新模块内部预算，不新增用户配置：

| 项目 | P0 实测 | 初始硬上限/超限处理 |
|---|---|---|
| 根数 N | Farming 182；CTI-kubejs 183；CTI-nokubejs 179 | 512；首次根 help 后停止，不发送 targeted |
| 总请求数 | 分别 368/370/362，均等于 `2N+4` | `2N+4`，N=512 时 1028；发送下一请求前检查 |
| 单 A 响应片数 | 根 help 2–3 包；`help execute` 单包 | 256；失败关闭 |
| 单 A 响应字符/字节 | 根 help 6892–10875 字符、6912–10905 raw bytes | 1 MiB；失败关闭 |
| 整次扫描总片数/字节 | 未超上限；逐交换原始计数见 02，旧 targeted 字节未统一汇总 | 4096 片 / 16 MiB；失败关闭 |
| 单次 A/B 交换 RTT | 回环近似平均 0.45–0.66ms，最大约 41ms；旧时间戳有舍入误差 | 10 s（SEND_A 至收到 B）；失败关闭，不重发 |
| targeted 交换循环耗时 | 回环 0.02–0.08s，仅覆盖 N 次 targeted | 不能用于校准完整扫描预算 |
| 完整墙钟耗时 | 本轮未记录；P6 必须补采首次根 help、empty-detail、末次根 help 和尾随后的总值 | 300 s（含最后交换前预留的尾随窗口）；失败关闭，不重发 |
| 最后 B 后尾随窗口 | 本次 5s 无包；实现候选至少 1.5s | 内部毫秒预算，受整次扫描剩余预算限制；窗口内收到包失败，静默到期完成 |

P0 的原始包序列、空包、锁、后续命令隔离和并发重复证据见 `research/02-rcon-ab-probe.md`。`help execute` 只按实际长度记录，不预设其必然多包；双客户端竞争只作故障观察，不作为并发安全证明。若实测需要放宽上限，必须先回设计说明理由，不得在实施中静默放大。

P0 证据已落入 `.trellis/tasks/10-25-rcon-help-command-fallback/research/02-rcon-ab-probe.md`：三组副本的 N、`2N+4` 请求数、根 help 包/字符/字节、RTT、targeted 交换循环耗时、5 秒尾随窗口、外部写入者前提及后续命令隔离均已记录。完整墙钟耗时本轮未记录，必须由 P6 补采；旧探针字段的限制和修正解释也在该报告中，不重写原始 JSON。

## 8. 管理入口、环境门槛与查询

### 8.1 `/mc_kb_rcon_scan`

处理顺序固定为：

1. `_check_permission(event)`；无权限直接返回。
2. 检查 `self.rcon` 与 `self.kb` 是否可用；发布目录取 `self.kb.data_dir`。**不检查 `self.kb.enabled`，不要求 `mc_server_dir` 非空。**
3. 本机 `mc_server_dir` 可读取时，若 `kubejs/` 目录或 `mods/` 中可识别的 KubeJS jar 给出已安装证据，拒绝扫描并提示使用 `/mc_kb_dump`。没有发现证据不等于证明远程无 KubeJS。
4. 获取 `_rcon_scan_lock`，已有扫描则立即回执；通过后先 yield 开始/进行中的进度消息，并提示扫描期间暂停其他 RCON 写入者。
5. 调用 `self.rcon.scan_help_commands()`；失败回执包含阶段、失败根、已完成根数、请求数和耗时，旧快照不变。活动任务必须登记到当前插件实例，供 `terminate()` 取消并有界等待清理。
6. 成功后校验并非空，再发布到 `self.kb.data_dir`；最终回执包含根数、usage/redirect 条数、请求数、片数/字节数、耗时和发布路径。

跨机场景无法从本机目录完整证明 KubeJS 不存在；使用这条**独立、管理员显式指令**即表示管理员确认目标是 fallback 环境。此限制写入 README 和最终回执边界，不增加自动探测或新配置。若本机路径与远程目标并不对应，本地检查也只能作为保守提示，不能声称完成远程能力证明。

### 8.2 查询降级说明

`kb/commands.py` 对 RCON producer 统一说明：

- 一级子命令可还原，深分支是 help 压缩语法；
- RCON 可见性不等于玩家/当前调用者可执行；
- **纯根命令可能未收录，targeted 空响应不代表裸根不可执行。**

KubeJS 提示不变；合并规则仍为运行时同根使用运行时 usage、只继承内置 `desc/cat`。不得用根级 help 或内置 vanilla 语法补造 RCON 缺失的运行时纯根，也不把 RCON 结果描述成与 KubeJS 等价的完整树。

## 9. 验收映射与回滚

- AC1 只在移除 KubeJS 及必需附属 mod 的隔离副本验收；AC6 在有 KubeJS 的同版本隔离副本做结构化对照，不用 KubeJS 环境冒充 fallback 闭环。
- AC2 以真实多包 A/B id 序列和后续普通命令为依据；idle-drain 不是通过证据。
- AC3/AC4 的协议故障主要由离线 fake server 精确构造，真机验证正常链路；首尾根集合变化优先用确定性 fake-server 验收，不依赖临场 reload 的不稳定时序。任意中间删片、同根集热替换和外部 RCON 并发写入不列为可保证检测项。
- AC5 的管理入口必须有入口级测试或逐步人工证据，覆盖非管理员零 RCON、重复调用不排队、KubeJS 环境拒绝和失败/进度回执；至少一条经生产 `/mc_kb_rcon_scan` 验证。卸载/重载取消也要覆盖活动任务和 socket 清理。
- 每个实施阶段只回滚本阶段新增文件/方法/提示；已发布旧快照始终保留。探针和验收只操作隔离副本，恢复原实例脚本/配置不涉及世界数据。
