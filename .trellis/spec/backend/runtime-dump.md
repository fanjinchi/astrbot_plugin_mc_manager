# Runtime Dump Contract

> 交叉契约：KubeJS 产物 ↔ RCON 完成信号 ↔ 插件编排 ↔ builder 读取。改动任一段都要同步其它段。
> 实测与证据：`.trellis/tasks/archive/2026-10/10-23-runtime-dump-oneclick/research/01-rcon-trigger.md`。

## 1. Scope / Trigger

改以下任一项前先读本文件：`assets/runtime_dump.js`、`runtime_dump.py`、`kb/builder.py` 的
`_load_runtime_dumps`/`_read_dump_objects`、`kb/commands.py` 的命令快照校验/发布/查询、
`rcon_client.py` 的 `execute_async` 超时语义。

## 2. Signatures

| 层 | 契约 | 位置 |
|---|---|---|
| AstrBot 指令 | `/mc_kb_dump`（async generator，先 `_check_permission`，单飞锁） | `main.py:854-888` |
| 编排入口 | `RuntimeDumpRunner(server_dir, rcon).run(rebuild) -> str`，`rebuild` 是同步无参可调用（内部 `asyncio.to_thread`） | `runtime_dump.py:134/144` |
| RCON | `execute_async(command: str, timeout: float | None = None) -> str`；`None` 保持 aiomcrcon 默认 2s | `rcon_client.py:72` |
| KubeJS 命令 | `researchdump`，`requires(source => source.hasPermission(2))` | `assets/runtime_dump.js:147` |
| 写盘（物品类） | `JsonIO.write('runtime_dump/<kind>.json', {kind,count,entries})`，路径相对 `gameDirectory` | `assets/runtime_dump.js:109` |
| 写盘（命令树） | `rdCommandEntries(ctx)` → `JsonIO.write('runtime_dump/commands.json', ...)` | `assets/runtime_dump.js:57/125` |
| 完成反馈 | 单行 `[rd] DONE {"version","duration_ms","counts","failed"}`；整体异常 `[rd] FAIL <原因>` | `assets/runtime_dump.js:151-153` |
| builder 读取 | `_load_runtime_dumps(server_dir, data_dir, rows, warnings) -> dict`；`_read_dump_objects(path) -> list|None`；名为 `commands` 的 stem 直接跳过 | `kb/builder.py:167/142` |
| 命令快照发布/导入 | `publish_snapshot(snapshot, data_dir)`（mkstemp + `os.replace` 原子替换）、`import_snapshot(server_dir, data_dir) -> {status,count,roots,producer,warning}` | `kb/commands.py:143/169` |
| 命令快照读取/查询 | `load_snapshot(data_dir) -> (snapshot, warning)` 每次查询重读；`search_commands(keyword, limit, data_dir)` 聚合 | `kb/commands.py:226/386` |

## 3. Contracts

### 3.1 产物文件
```json
{"kind":"item","count":16043,"entries":[{"kind":"item","id":"ResourceKey[minecraft:item / ns:path]","tkey":"...","resolved":"...","stack":"..."}]}
```
- 文件名 `<kind>.json`，`kind ∈ {item,block,entity,fluid}`；某类 0 条或抛异常时**不写文件**（旧文件保留）
- `id` 是 `ResourceKey[...]` 形态，由 `_dump_id`（`kb/builder.py:132`）解析
- `stack` 仅 item；fluid 没有 `tkey/resolved`（字段可缺）；字段名冻结
- `JsonIO.write` **不建父目录**且是 truncate 写：插件必须先建 `<server>/runtime_dump/`（`runtime_dump.py:150-153`）

命令树是同一目录下的独立文件 `commands.json`（`RD_VERSION = '3'` 起）：
```json
{"kind":"commands","schema_version":1,"producer":"kubejs","count":2,
 "entries":[{"name":"wine","syntax":"wine age <years>","source":"unknown","level":null},
            {"name":"wine","syntax":"wine info","source":"unknown","level":null}]}
```
- 来源：`dispatcher.getAllUsage(dispatcher.getRoot(), ctx.source, false)`（活动 dispatcher，不缓存注册事件里的那个）。
  1.19.2 / 1.20.1（brigadier 1.0.18 / 1.1.8）实测输出一致：`foo`、`foo bar`、`foo <count>`、`alias -> foo`、`loop ...`。
- redirect 行拆成 `syntax`（指向路径）+ `redirect`（目标 literal 或 `...`），不作为可执行语法导出。
  目标是**外部 dispatcher 的 root** 时 Brigadier 输出 `prefix ->`（目标 usageText 为空），同样记为 `redirect="..."`。
- 命令树导出失败或 0 条：`counts.commands` 不写入、`failed` 追加 `commands`，**不写空文件**，旧快照保留。
- 命令条目不计入物品 dump 文件数：`_load_runtime_dumps` 在空文件告警**之前**跳过 stem 为 `commands` 的文件
  （否则会抑制 `kubejs_hint`、虚报 dump 文件数，0 字节的空快照还会进物品告警）。
- `gameDirectory` 必须等于 `mc_server_dir`（启动脚本先 `cd`），否则文件写到别处

### 3.1.1 查询语义（两种 producer 共用）
- 关键词按空白、下划线、连字符拆成**无序 token**，连续分隔符不产生空 token；比较时两侧都忽略空白/下划线/连字符，
  所以 `channel mode` / `channel_mode` / `channel-mode` 都能命中 `channelmode`（`kb/commands.py:320/325`）。
- 根级采用**全 token AND**：每个 token 至少命中该根的 name/desc/usage/redirect 之一才返回；可以分别落在不同字段。
- 普通 usage 只有**同一条语法覆盖全部 token** 才进入优先展示（`matched`），否则不因多词查询把无关 usage 顶到最前。
- 精确/前缀/包含三档用整条归一化查询与根名比较（`_rank`），runtime 与 vanilla 共用同一口径。
- `->` 是 redirect 结构标记：分词前用哨兵保护不被拆开；显式 `->` 只匹配 redirect 结构，不拿 name/usage/desc 凑命中。
  redirect 仅作别名提示，永不进入普通 `matched` usage。
- 已知限制：多 token 查询的整条归一化串通常不等于/不前缀于根名，因此多词查询多半落在第 4 档、
  按根名排序；短 token（如 `mc`）在忽略分隔符后可能跨词边界假命中（`team create`）。单根 8 条上限不变。
- **KubeJS `/reload` 会丢非 `RegisterCommandsEvent` 注册的命令**（2026-10-28 实测，CTI 副本）：reload 前 `help ae2`
  正常返回、reload 后变 `Unknown command or insufficient permissions`；同一副本首轮导出 184 根 / 2038 条，
  重启后不 reload 再导出 188 根 / 2061 条。首次部署 `runtime_dump.js` 必触发 `/reload`，因此首轮快照可能缺这类根；
  需要完整命令树时应在脚本已部署（不再 reload）的稳定态导出，或部署后重启服务器再 dump。

### 3.2 完成信号
- RCON 响应 = 命令执行结束后 `RconConsoleSource` 的缓冲，所以 `[rd] DONE` 出现即完成；**不用标记文件、不轮询、不做就绪探测**
- 判定顺序：先 `DONE_PREFIX`/`FAIL_PREFIX`，再 Unknown，最后才是「无反馈」（顺序颠倒会重复执行 dump）

### 3.3 RCON 超时语义（`rcon_client.py:72-125`）
- `timeout=None` 不传参（保持 2s 默认），现有调用方行为不变；长命令显式放大（dump 180s、`/reload` 120s）
- 超时 → 重连丢弃挂起响应，**绝不重发**（否则长命令执行两次）
- 登录阶段超时（`sent=False`）单独报「RCON 登录超时…命令未发送」，不能套用命令超时文案
- `_send_lock` 串行同一 socket：dump 期间其它 RCON 命令排队

## 4. Validation & Error Matrix

| 触发响应 | 判定 | 回执 |
|---|---|---|
| `[rd] DONE {...}` 可解析 | 成功 | 各类别条数 + 重建结果 |
| `[rd] DONE` 但 JSON 坏 | 未收到 DONE | 提示查 `logs/kubejs/server.log` |
| `[rd] FAIL ...` | 失败 | 失败原因 + 日志路径 |
| `Unknown ...` | 命令未注册 | 2s×15 退避；耗尽回执手工 `/reload` + 四步 |
| 无 DONE/FAIL/Unknown | 首次重试一次（兼容旧 v1 脚本/反馈丢失），第二次如实回执 | 未收到 DONE |
| `错误: 无法连接到服务器` | RCON 断连 | 手工四步，不再触发 |
| `错误: 命令响应超时` | 命令可能已执行 | 不要重复触发，查日志 |
| `错误: 其它`（鉴权/协议） | 命令未执行 | `RCON 执行失败：<原文>` |
| 无 `kubejs/`、目录/脚本不可写 | 环境不满足 | 对应中文原因 + 手工四步 |

## 5. Good / Base / Bad Cases

- **Good**：脚本内容一致 + DONE → 只发 `researchdump`、不 reload（线上实测 322ms）
- **Base**：首次部署 → 写脚本 + `/reload`（约 3.5s tick 积压）→ Unknown 退避 → DONE → 自动重建
- **Bad**：`runtime_dump/` 不存在 → 四类全部 `NoSuchFileException`、JS 返回 `failed` 列表且文件不生成；builder 无文件可并

## 6. Tests Required

- `_parse_dump_summary`：正常 / 缺字段 / 坏 JSON / 无前缀
- `_rcon_error_kind`：断连 / 超时 / other / 正常文本
- `_trigger`：Unknown→DONE、Unknown 耗尽、FAIL、无反馈首次重试、断连/超时/other
- `execute_async`：超时单发、`timeout=None` 仍 2s、发送锁串行、登录超时区分
- `_load_runtime_dumps`：`.json` 优先、截断 warning、0 字节 warning、`_` 前缀、非 dump JSON、
  跳过 `commands`（含 0 字节 `commands.json` 不产生物品告警）
- `kb/commands.py`（`tests/test_commands.py`）：快照校验（kind/version/producer/count/name-syntax）、去重排序、
  原子替换失败保留旧快照（无残留临时文件）、导入 missing/published/invalid/error、legacy JSONL 仅无 canonical 时读取、
  根合并（只继承 desc/cat，source/level 未知）、**合并根必须能用继承的中文 desc 搜到**（回归 P0）、仅根 usage、
  根+子 usage、redirect 提示、限流按根计数、8 条用量上限、`producer=rcon` 降级提示、坏快照告警、
  快照存在时的无结果文案、物品重建失败时命令告警仍进回执、
  **多词无序 token AND**（分隔符等价、`->` 结构 token、竞争根只覆盖部分 token 时不得误返回）、
  同一条 usage 覆盖全部 token 才优先展示（`mek` 基线折叠 vs 多词命中上浮）、
  继承中文 desc 与 usage 的跨字段命中不拼成 matched usage、同义缺口查询（`clear radiation`）允许无结果
- `_format_counts`（`tests/test_runtime_dump.py`）：commands 不并入物品总数
- `assets/runtime_dump.js`（`tests/test_dump_script.py` + `tests/js_dump_harness.js`，Node 桩执行真实脚本）：
  五类产物、RD_VERSION=3、五种 usage 形态（含外部 root 的 `prefix ->`）、dispatcher 抛错时只污染 `failed`、产物过 Python 契约校验
- **尚未覆盖（待补）**：`_trigger` 的 Unknown→DONE / 重试 / 失败分支与 `execute_async` 的 socket 级超时语义。
  前者需要 fake RCON 客户端，后者依赖真实连接；目前靠真机验证，写用例时不要 mock 掉被验证的语义。

## 7. Wrong vs Correct

- **Wrong**：`[rd] FAIL ... unknown ...` 先按 Unknown 处理 → 重试 16 次、重复执行 dump
  **Correct**：先判 `DONE_PREFIX`/`FAIL_PREFIX`，再判 Unknown（`runtime_dump.py:242`）
- **Wrong**：超时后重发命令（旧 `TRANSIENT_RCON_ERRORS` 吞掉 `TimeoutError`）→ dump 执行两次
  **Correct**：`asyncio.TimeoutError` 前置捕获、只重连不重发（`rcon_client.py:105`）
- **Wrong**：把 `.json` 当 `.jsonl` 逐行读 → 整文件 JSON 永远解析失败
  **Correct**：按后缀分流（`kb/builder.py:148-164`）
- **Wrong**：把命令条目的 `name`（根 literal）当物品 id 或把 `commands.json` 计进物品 dump 文件数
  **Correct**：`_load_runtime_dumps` 直接跳过 `commands` stem，命令快照只由 `kb/commands.py` 消费
- **Wrong**：查询时用模块级缓存保存命令快照 → `/mc_kb_dump` 后不重启看不到新命令
  **Correct**：每次查询重读已发布文件（`_vanilla_cache` 只用于随插件分发的固定清单）
- **Wrong**：运行时同根继承内置 `desc` 只用于显示、打分时仍只看 name/usage → 快照保存过全部原版根后，
  中文描述搜索整体失效（内置行已被同根跳过）
  **Correct**：`desc` 与 usage 一起参与匹配（`kb/commands.py` 的 `_score_runtime`），并保留"合并根能按中文 desc 命中"的回归用例
- **Wrong**：多词查询按整串包含匹配（`quest editing` 只有词序恰好连续才命中），或把"根里任意 usage 命中任一 token"算作优先展示
  **Correct**：拆成无序 token 做根级 AND，只有同一条语法覆盖全部 token 的 usage 才进 `matched`
- **Wrong**：归一化时直接用 `-`/空格 split 拆 `->`，或把显式 `->` 当普通子串去匹配 name/usage
  **Correct**：`->` 用哨兵保护整体保留，显式 `->` 只匹配 redirect 结构（`kb/commands.py:346-351`），
  且 redirect 不进入普通 `matched` usage
- **Wrong**：首次部署脚本触发 `/reload` 后立刻导出，并假定 dispatcher 完整（实测 AE2 根在 reload 后消失，快照少 4 根 / 23 条）
  **Correct**：脚本已部署、未触发 reload 的稳定态导出；部署后重启服务器再 dump，并在 README 说明该限制
