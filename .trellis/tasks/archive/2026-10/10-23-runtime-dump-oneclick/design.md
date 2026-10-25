# 设计：运行时 dump 一键化（方案 B：KubeJS JsonIO 直写文件 + 命令反馈作完成信号）

> 经四轮评审修订（2026-10-24 第四轮：删除标记文件与轮询）；**已用原型在线上服实测**（JsonIO 写盘、RCON 响应回传 `sendSystemMessage`、reload 后 Unknown 窗口、reload 约 3.4s tick 积压；见 research 第 8 节）。承重事实与可复查证据见 `research/01-rcon-trigger.md`：KubeJS 1902 类过滤器**禁止 `java.io`/`java.nio`**（仅放行 Closeable/Serializable/ByteOrder）；`JsonIO` 是官方允许的写盘绑定（`write(Path, JsonObject)`，字符串经 TypeWrapper 转 Path）；`KubeJS.verifyFilePath` 只要求写在 gameDirectory 内；`JsonIO.write` **不建父目录**、**truncate 写**、tab 缩进 pretty；Rhino 自带 `mm.jsmappings`（1.19.2 Mojmap→SRG 重映射）；**RCON 会阻塞到命令执行结束并回传命令反馈**（`DedicatedServer.m_7261_` + `RconConsoleSource`，静态确证）——因此完成判定用命令反馈，不用标记文件。

## 边界与职责

- **新模块 `runtime_dump.py`**（插件根目录）：dump 编排核心。logger 沿用 `kb/__init__.py` 的 ImportError fallback，可脱离 AstrBot 独立测试。
  - `RuntimeDumpRunner(server_dir, rcon)`：编排 `预检 → 预建目录 → 部署(按需) → /reload → 触发并解析反馈 → 回执`；单飞锁为**插件级单例**（`main.py.__init__` 创建），由 main 用 `async with self._dump_lock` 包住 Runner 调用（Runner 不持有、不释放锁）。
  - 纯函数：`_parse_dump_summary(resp)`（从 `[rd] DONE {...}` 解析统计）、`_response_says_unknown(resp)`、`_rcon_error_kind(resp)`（区分「无法连接/响应超时/其它」）、`_script_deploy_needed(...)`（内容比对），便于本地单测。
- **`main.py` 新增 `/mc_kb_dump` 指令**：照搬 `/mc_kb_rebuild` 模式——`_check_permission` → `self.kb is None` / `kb.enabled` 检查 → 立即回执「⏳ 进行中」→ 异步编排 → `asyncio.to_thread(self.kb.rebuild)` → 最终回执统计。**注意权限语义**：`admin_ids` 为空时 `is_admin` 返回 True（现状），回执文案与方法说明不要宣称「管理员专属」。
- **`rcon_client.py`（本轮允许改动）**：
  - `execute_async(command, timeout=None)`——`timeout=None` 时**不传参**给 `send_cmd`（保持自带 2s 默认，现有调用方行为不变）；传值时透传（dump 用 180s、reload 用 120s）。
  - `asyncio.TimeoutError` 在 TRANSIENT 捕获**之前**单独捕获 → 重连但绝不重发，返回 `"错误: 命令响应超时（>Xs，命令可能已在服务器执行）"`。
  - **新增 `self._send_lock = asyncio.Lock()`**，`send_cmd` 段用 `async with` 串行化：长命令期间其它调用排队，避免同一 socket 上响应错位/半包触发重连重发（最坏双 dump）。
  - `test_connection_async` 里的 `client.send_cmd("list")` 也走同一把 `_send_lock`（或改为复用 `execute_async`），否则 dump 期间 `/test_connection` 仍会抢连接。
- **`assets/runtime_dump.js`（重写为 v2）**：双版本 Registry 兼容 + `JsonIO` 直写 `<kind>.json` + 命令结束回传单行统计（`[rd] DONE/FAIL`）+ 权限门槛。**无任何标记文件、无顶层写盘**。
- **`kb/builder.py`（本轮允许改动）**：`_load_runtime_dumps` 增加 `.json` 读取——同时认 `.json`/`.jsonl`（`stem` 分别 `fn[:-5]`/`fn[:-6]`）、跳过 `_` 前缀、`.json` 读 `{kind,count,entries}`、**每个文件独立 try/except**（损坏/截断→warning+跳过）、同名类别 `.json` 优先于 `.jsonl`。jsonl 兼容保留。**损坏文件告警接入 `builder.rebuild` 的 `warnings`**（`_load_runtime_dumps` 现签名只有 3 参，需新增参数或返回 warnings 并在调用处合并）；`.json` 读取器只处理含 `entries` 的对象，非 dump JSON（如未来 `commands.json`）跳过，`kb/commands.py` 的 `commands.jsonl` 通道不动。
- **`assets/extract_runtime_dump.py` 删除**：方案 B 下无提取层（git 历史可查）。
- **不改动的部分**：`log_watcher.py`、`kb` 其余模块（**例外**：`kb/query.py:124-126` 的 `/mc_kb_status` 提示文案改为指向 `/mc_kb_dump` 与 `*.json`，2 行）。

## 核心流程

```
/mc_kb_dump（受 admin_ids 控制，空=所有人）
  ├─ 前置检查：kb 可用 → mc_server_dir 存在 → kubejs/ 目录存在（否则手工四步降级文案）
  ├─ 单飞锁：已有 dump 在跑 → 回执拒绝（main async with 持有/释放）
  ├─ 预创建 <server_dir>/runtime_dump/（JsonIO.write 不建父目录；失败回执带 mkdir -p 命令）
  ├─ 懒部署：比对 kubejs/server_scripts/runtime_dump.js 与插件 assets 内容
  │    └─ 缺失/不一致 → 写入 → RCON /reload（timeout=120s；响应不代表完成）
  │         └─ 响应为「错误: 无法连接…」→ 回执 RCON 不可用 + 手工四步（不再触发）
  ├─ 触发 + 完成判定（一次 RCON 调用，timeout=180s；响应即结果）：
  │    ├─ 含 "Unknown" → sleep 2s 重试（最多 15 次 / 30s）
  │    │    └─ 30s 仍 Unknown → 回执诊断（查看服务器日志；**不要再发 /reload**）
  │    ├─ 含 "[rd] DONE {...}" → 解析 counts/failed/duration_ms，进入重建
  │    ├─ 含 "[rd] FAIL ..." → 回执失败原因
  │    ├─ 「错误: 无法连接…」→ 立即回执 RCON 失败 + 手工四步
  │    ├─ 「错误: 命令响应超时…」→ 回执失败（dump 未在 180s 内结束，查 watchdog/日志）
  │    └─ 其它/空响应 → 回执「命令已执行但未收到 DONE 标记」，提示查 logs/kubejs/server.log
  ├─ asyncio.to_thread(self.kb.rebuild) 自动重建（builder 合并 runtime_dump/*.json 与 *.jsonl）
  └─ 回执：各类别条数 + failed 类别 + 耗时 + 重建结果摘要
```

> 说明：第一次触发若返回 `Unknown`，说明 `/reload` 还没把命令注册好，本次调用不会执行 dump；重试到可用时的那一次就是正式触发。就绪确认与触发是同一个动作，不需要额外标记文件或独立 probe。

## runtime_dump.js v2 要点

- **双版本 Registry**：`try { Java.loadClass('net.minecraft.core.registries.BuiltInRegistries') } catch → Java.loadClass('net.minecraft.core.Registry')`（成员访问用 Mojmap 名，Rhino 重映射兜底）。
- **直写文件（JsonIO）**：`JsonIO.write('runtime_dump/<kind>.json', {kind, count, entries})`——**字符串直传**：KubeJS 的 TypeWrapper 自动把字符串经 gameDirectory 相对解析 + `verifyFilePath` 转成 Path、把 JS 对象字面量转成 JsonObject（已 javap 确认 Path/JsonObject 的 TypeWrapper 均注册；`Utils` 全局绑定是 `UtilsWrapper` 接口，**没有** `getPath`，绕道 `Java.loadClass('...UtilsJS')` 还有 `getPath(String)` 重载陷阱，都不要用）。路径限制已排除：只要求写在 Minecraft 目录内，`<server>/runtime_dump/` 允许。
- **目录前提**：JS 无法建目录（java.io/nio 被禁），**手工流程必须先 `mkdir -p <server>/runtime_dump`**；自动流程由插件预创建。
- **某类抛异常或 0 条时不写该文件**——旧文件保留；但 `JsonIO.write` 是 truncate 写：写到一半失败/崩服会留下截断文件，builder 侧必须单文件容错（见下）。
- **条目 schema 冻结**：`{kind, id, tkey, resolved, stack}`（fluid 无 tkey/resolved）——与 `kb/builder.py` 的 `_dump_id` 读取逻辑对齐，字段名不许改。
- **完成反馈（替代标记文件）**：命令回调末尾 `ctx.source.sendSystemMessage(Component.literal('[rd] DONE ' + JSON.stringify(summary)))`，`summary` 含 `counts/failed/duration_ms`；整体异常发 `[rd] FAIL <原因>`。**单行、< 4KB**（RCON 单包上限）；可同时 `console.info` 一份到服务器日志便于诊断。
- **权限门槛**：`.requires(src => src.hasPermission(2))`（SAM 转换同 v1 的 `.executes`；requires 在解析期过滤，低权限 source 见 "Unknown command"，RCON 4 级不受影响）。
- 头注释更新：**四步**用法（`mkdir -p runtime_dump` → 拷 JS 并重启/`/reload` → **OP/控制台**执行 `/researchdump` → `/mc_kb_rebuild`），标注 1.19.2/1.20.1+ 双版本兼容。

## 关键取舍

- **JsonIO vs java.io 直写**：java.io 被 KubeJS 类过滤器禁止（确证），JsonIO 是官方允许路径。落盘从 jsonl 变单文件 JSON，由 builder 直接读——**不做插件侧转写层**；手工降级因此是**四步**（多一步建目录）。
- **builder 改 vs 不改**：选「builder 加 `.json` 读取」。不是「加个后缀」：需同时改后缀过滤、`stem` 切片、整文件 `entries` 解析、`_` 跳过，并补单文件容错。换来端到端无转写层、手工/自动两条路同构；`.jsonl` 读取保留，旧产物兼容。
- **完成判定用命令反馈而非标记文件**：`/reload` 后命令表要等 `ReloadableServerResources`/`Commands` 重建（脚本加载早于它，静态确证），所以任何「脚本已加载」标记都不能证明命令可用；而 RCON 调用本身会阻塞到命令结束并回传反馈（`DedicatedServer.m_7261_` → `executeIfPossible` `join` → `RconConsoleSource.getCommandResponse()`）。一次调用同时完成「就绪确认 + 触发 + 完成判定」，省掉 `_done.json`/`_loaded.json`、轮询、半写标记容错与就绪竞态。
- **Unknown 即重试**：命令未注册时 RCON 立即返回 Unknown（不执行 dump），退避重试成本低；不需要额外的 probe 命令或标记文件。
- **watchdog**：不预先分片。**复制服全量实测** 27,643 条、`duration_ms` 295ms、约 6.2MB（item 4.01MB / block 1.86MB / entity 150KB / fluid 144KB），远低于 60s（线上 `max-tick-time=60000` 确证）；验收阈值 `duration_ms < 30s` 且无 watchdog 告警。`/reload` 的代价另计（原型实测约 3.4s tick 积压），实测挑低峰、避开 FTB Backups 整点/半点。

## 兼容与回滚

- `rcon_client.py`：可选参数 + 超时分支 + 发送锁，现有调用方行为不变（默认 2s）。
- `kb/builder.py`：纯增量（新增 .json 读取 + 容错 + `_` 前缀跳过），jsonl 路径不变。
- JS v2 同时兼容 1.19.2 与 1.20.1+；手工四步（mkdir → 拷 JS + 重启/`/reload` → OP/控制台 `/researchdump` → rebuild）降级全程可用。
- 回滚 = git 还原插件侧改动；服务器侧删 `kubejs/server_scripts/runtime_dump.js` 与 `runtime_dump/`。**注意**：已注册的 `/researchdump` 会保留到下次 `/reload` 或重启，删文件后需 reload 才彻底消失。

## 风险

- **RCON 触发 KubeJS 命令失败**（研究问题 1）：实测确认；兜底降级 = 玩家进服执行一次 `/researchdump`，其余全自动。
- **就绪竞态**：命令表晚于脚本加载生效 → 触发调用里的 `Unknown` 退避重试兜底（2s×15=30s；若实测 reload 更慢，把窗口调到 60s，见 research 待实测）；仍失败时回执诊断，不二次 reload。
- **反馈丢失**：命令已执行但 `sendSystemMessage` 未回传（脚本中途抛错/反馈超长）→ 回执「未收到 DONE 标记」，提示查日志；不会误判为成功。
- **`<kind>.json` 截断**：`JsonIO` truncate 写，崩服/写失败会留半截文件 → builder 单文件容错（跳过 + warning），不拖垮整次重建。
- **RCON 并发**：发送锁串行化；dump 期间其它命令排队而非抢包。
- **旧 `.jsonl` 与新 `.json` 共存**：json 优先；README 提示清理旧 jsonl，并把跨机段「同名取 mtime 新」的说法一并更新。
- **权限语义**：`admin_ids` 为空=所有人可用；回执与文档不得写「仅管理员」。
- **性能**：复制服全量实测 dump 仅 295ms / 6.2MB（对 tick 几乎无感）；真正的卡顿来自 `/reload`（原型实测 1 人在线时约 3.4s tick 积压，日志 `Can't keep up`），仅首次部署/脚本变更时发生。低峰/空服执行，避开备份。
- **不同机**：仅支持同机写脚本；不同机只给手工文案（含 `mkdir`）。
