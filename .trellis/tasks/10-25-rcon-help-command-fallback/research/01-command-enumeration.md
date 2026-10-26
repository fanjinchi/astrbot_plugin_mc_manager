# 无 KubeJS 命令枚举方案调研

## 结论

无 KubeJS 时优先评估 RCON 执行 vanilla `help`，因为其数据来自当前 Brigadier `CommandDispatcher`。被动日志和 JAR 静态扫描均不能作为可靠、完整的命令语法生产者。

本期保持 KubeJS 结构化导出为主路径。RCON fallback 必须先解决完整多包接收、两阶段采集（根 + 一级子命令）、无换行解析和原子缓存，不能直接复用当前单次 `execute_async("help")` 就算完成；其语法是 smart usage 的降级形式（见 2026-10-25 复核修订）。

## 一手证据

### 对应版本服务端

只读反编译检查：

- Forge 1.19.2：`/home/guigui/mc/CTI0.46/libraries/net/minecraft/server/1.19.2-20220805.130853/server-1.19.2-20220805.130853-srg.jar`
- Forge 1.20.1：`/home/guigui/mc/Farming/libraries/net/minecraft/server/1.20.1-20230612.114412/server-1.20.1-20230612.114412-srg.jar`
- 两者均检查 `net/minecraft/server/commands/HelpCommand.class`、`RconClient`、`RconConsoleSource`。

行为：

| 输入 | 机制与结果 |
|---|---|
| `help` | 对 root 调用 `getSmartUsage(root, source)`，得到当前 source 可见根命令及压缩语法 |
| `help <command>` | parse 输入 → 取最后解析节点 → `getSmartUsage(node, source)`，逐条打印 `/输入原文 + 一级子命令 smart usage`（**不是** `getAllUsage`，见下方 2026-10-25 复核修订） |
| `help 1` / `help 2` | 将数字当命令名解析；两个目标版本均不能据此实现分页 |

`getAllUsage(node, source, restricted)` 仅在 `restricted=true` 时检查 `canUse(source)`；`restricted=false` 不执行该可见性过滤。它输出有 `command` 的完整已注册路径，并对 redirect 给出 `...` 或 `-> target`（KubeJS 主路径用它），但不保证当前调用者必然可执行。smart usage 会压缩分支，不能视为完整参数导出。

本地实例 `/home/guigui/mc/Farming/mods/[葡园酒香] letsdo-vinery-forge-1.4.41.jar` 的 `WineDebugCommands` 同时有 `wine age <years>` 与 `wine info`；只保留根级 `(age|info)` 会丢失 `<years>`，证明需要 targeted help。

两个版本的 `RconConsoleSource` 均以权限等级 4 构造。HelpCommand 只反映该 source 的 `requires` 可见性；模组仍可能在 `executes` 内要求玩家，因此 help 可见不等于控制台必定执行成功。

### 2026-10-25 复核修订：`help` 不是 `getAllUsage`

原始调研把 `help <command>` 记为 `getAllUsage(node, source, true)`，本次复核推翻了该结论，子任务 PRD 已按**降级口径**改写（R5、AC1–AC3）。

证据（本机可复现）：

- `javap -p -c` 两个版本的 `HelpCommand`：1.19.2 的带参 `m_137789_` 与无参 `m_137792_`、1.20.1 的带参/无参执行方法均只调用 `CommandDispatcher.getSmartUsage`，整个类没有任何 `getAllUsage` 调用；输出模板为 `/%s %s`（带参）与 `/%s`（无参）。
- 带参分支逻辑 = `dispatcher.parse(输入)` → 取 `ParsedCommandNode` 最后一个节点 → `getSmartUsage(node, source)` → 每条打印 `"/" + 输入原文 + " " + smart usage`。
- 用本地 `brigadier-1.0.18.jar` 构造最小命令树实测：

```
help（无参）  → /wine (age|info)     /branched (a|b)     /tm -> tell     /self ...
help wine     → /wine age <years>    /wine info
getAllUsage   → wine age <years>     branched a x        tm -> tell      self ...
```

可得数据边界：

- 根级 `help`：只到根命令 + 压缩子树，深分支丢失（`branched a x/y` 变成 `(a|b)`，`wine age <years>` 变成 `(age|info)`）。
- `help <root>`：把目标节点的**一级子命令**逐条展开，浅树可完整还原（`wine age <years>` / `wine info`）；更深分支仍压缩为 `(a|b)`、可选组 `[x]`、redirect `-> target`、redirect-to-root `...`。
- 目标节点没有可见子命令时 map 为空 → **RCON 收到空响应是合法结果**（表示该根没有可见一级子命令 usage），不得按解析失败处理；必须保留根级 `help` 已采集的该根条目，不能误删或把整次采集当成空快照。
- smart usage 的 `[可选]`/`(a|b)` 无法还原成 Brigadier 的 required/optional 语义；不得声称与 KubeJS 主路径等价。

### RCON 传输

- 两个版本的 `RconClient` 会对超过 4096 个 Java 字符的响应分片；1.19.2 对应 `RconClient.java:124–135`，1.20.1 对应 `126–137`。
- `RconConsoleSource` 发送多条反馈时不追加换行，原始文本可能形如 `/usage-one/usage-two`。
- 当前依赖 `aio-mc-rcon 3.5.0`：`/home/guigui/code/AstrBot/.venv/lib/python3.12/site-packages/aiomcrcon/client.py` 的 `_send_msg` 在 78 行，95/98 行只读取一个长度和一个响应体，112 行直接返回；`send_cmd` 在 114 行。
- 本插件 `rcon_client.py` 仅调用 `client.send_cmd(command)`。现有锁只防止并发发送，不能接收全部分片或清理残留响应。

因此必须先实现按 request id 的有界完整接收和结束判定。失败时应重连并放弃快照，不能保存截断结果或让残片进入下一条命令。

## 方案比较

| 方案 | 可得数据 | 可靠性/成本 | 决策 |
|---|---|---|---|
| KubeJS dispatcher 导出 | 结构化命令树、完整 usage | 高保真；复用现有管道，低—中成本 | 主路径 |
| RCON root + targeted help | RCON 可见根及一级子命令 smart usage（非 getAllUsage） | 运行时真实；多包、N+1、解析与一致性成本中—高 | 无 KubeJS 首选 fallback（降级口径） |
| 被动 `latest.log` | 偶发注册消息、mod 列表，通常无参数结构 | 覆盖不可判定、格式任意、旧日志风险 | 排除 |
| 静态 JAR | 简单 builder 的部分 literal/argument | 动态注册、配置、反射、映射/混淆导致误报漏报；成本很高 | 不作为生产方案 |
| 已有控制台接口 | 同样来自 HelpCommand，逐行输出可能更易解析 | 面板协议无统一标准 | 已有能力时才考虑 |
| 可选 Forge 导出 mod | 结构化 dispatcher | 高保真但需安装、分发和多版本维护 | 仅 fallback 实测不达标时重评 |

被动日志的具体反例：Farming 的 Vinery 日志只有 `Registered /wine command`，而字节码实际还有 `age <years>` 和 `info`，无法从日志还原。

KubeJS 动态命令的具体反例：`/home/guigui/mc/CTI0.46/kubejs/server_scripts/runtime_dump.js:89` 注册 `researchdump`，静态扫描 mod JAR 看不到它。

## 采集与发布约束

1. 根级 `help` 用于发现并提供根级 smart usage；逐根 `help <root>` 提供该根的**一级子命令** usage，更深分支是 smart usage 压缩语法，快照必须标记 `producer=rcon` 且不得宣称完整。阶段二 design 必须明确根级与 targeted 结果的合并/去重规则，合法 `syntax == name` 不得过滤。
2. 不依赖 `splitlines()`；按 `/` 切分并用已知根前缀校验；空响应表示该根没有可见一级子命令 usage，不算异常，并保留根级 `help` 中该根的已有条目；异常结构才失败。离线夹具需覆盖 root-only、`foo` / `foo bar` 并存和 empty-targeted。
3. 不依赖固定英文错误消息；unknown/localized error 和自定义 help 必须通过能力探针与结构校验处理。
4. 全部目标根成功后才一次性替换缓存；失败保留旧有效快照。
5. 限制请求数、响应大小和总耗时；扫描期间 reload 或快照不一致时不得发布混合结果。
6. 参数类型、数值范围、精确权限和 mod 归属不属于本期保证。

## 后续最小实测

本调研未连接在线服务器，以下实验须在获批测试实例执行：

1. 在 1.19.2、1.20.1 记录 root/targeted help 原始包、request id、包数、总字符数与结束判定；覆盖超过 4096 字符和 `help execute`。
2. 用 `help help`、`help 1` 和不存在命令检测 help 是否被覆盖及当前错误形态，不实现分页循环。
3. Farming 对比 `help` 与 `help wine`：`help wine` 应给出 `/wine age <years>` 与 `/wine info`，根级 `help` 只给压缩形式；CTI 检查 `help researchdump` 的动态命令可见性；记录终端命令 `help <root>` 的空响应，以及只有根 usage、根与子 usage 并存和 empty-targeted 时的合并结果，确认空响应不删除根级条目。
4. 与同一时刻的结构化 dispatcher 导出比较根集合与一级子命令集合，记录深层压缩差异、权限过滤、玩家限制与 parser 错误，并记录 N+1 耗时。
5. 模拟缺包、错 request id、非预期文本和中途断连，验证旧缓存保留且后续 RCON 响应不受污染。

## Sources

- [Mojang Brigadier 1.0.18 — CommandDispatcher.java](https://github.com/Mojang/brigadier/blob/1.0.18/src/main/java/com/mojang/brigadier/CommandDispatcher.java)
- [Mojang Brigadier 1.1.8 — sources JAR](https://libraries.minecraft.net/com/mojang/brigadier/1.1.8/brigadier-1.1.8-sources.jar)
- [MinecraftForge 1.20.x — RegisterCommandsEvent.java](https://github.com/MinecraftForge/MinecraftForge/blob/1.20.x/src/main/java/net/minecraftforge/event/RegisterCommandsEvent.java)
- [MinecraftForge 1.19.x — RegisterCommandsEvent.java](https://github.com/MinecraftForge/MinecraftForge/blob/1.19.x/src/main/java/net/minecraftforge/event/RegisterCommandsEvent.java)
- [aio-mc-rcon 源码仓库](https://github.com/Iapetus-11/aio-mc-rcon)
