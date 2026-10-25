# Runtime Dump Contract

> 交叉契约：KubeJS 产物 ↔ RCON 完成信号 ↔ 插件编排 ↔ builder 读取。改动任一段都要同步其它段。
> 实测与证据：`.trellis/tasks/10-23-runtime-dump-oneclick/research/01-rcon-trigger.md`（任务归档后仍在）。

## 1. Scope / Trigger

改以下任一项前先读本文件：`assets/runtime_dump.js`、`runtime_dump.py`、`kb/builder.py` 的
`_load_runtime_dumps`/`_read_dump_objects`、`rcon_client.py` 的 `execute_async` 超时语义。

## 2. Signatures

| 层 | 契约 | 位置 |
|---|---|---|
| AstrBot 指令 | `/mc_kb_dump`（async generator，先 `_check_permission`，单飞锁） | `main.py:853-887` |
| 编排入口 | `RuntimeDumpRunner(server_dir, rcon).run(rebuild) -> str`，`rebuild` 是同步无参可调用（内部 `asyncio.to_thread`） | `runtime_dump.py:130/141` |
| RCON | `execute_async(command: str, timeout: float | None = None) -> str`；`None` 保持 aiomcrcon 默认 2s | `rcon_client.py:72` |
| KubeJS 命令 | `researchdump`，`requires(source => source.hasPermission(2))` | `assets/runtime_dump.js:91` |
| 写盘 | `JsonIO.write('runtime_dump/<kind>.json', {kind,count,entries})`，路径相对 `gameDirectory` | `assets/runtime_dump.js:74` |
| 完成反馈 | 单行 `[rd] DONE {"version","duration_ms","counts","failed"}`；整体异常 `[rd] FAIL <原因>` | `assets/runtime_dump.js:95-97` |
| builder 读取 | `_load_runtime_dumps(server_dir, data_dir, rows, warnings) -> dict`；`_read_dump_objects(path) -> list|None` | `kb/builder.py:167/142` |

## 3. Contracts

### 3.1 产物文件
```json
{"kind":"item","count":16043,"entries":[{"kind":"item","id":"ResourceKey[minecraft:item / ns:path]","tkey":"...","resolved":"...","stack":"..."}]}
```
- 文件名 `<kind>.json`，`kind ∈ {item,block,entity,fluid}`；某类 0 条或抛异常时**不写文件**（旧文件保留）
- `id` 是 `ResourceKey[...]` 形态，由 `_dump_id`（`kb/builder.py:132`）解析
- `stack` 仅 item；fluid 没有 `tkey/resolved`（字段可缺）；字段名冻结
- `JsonIO.write` **不建父目录**且是 truncate 写：插件必须先建 `<server>/runtime_dump/`（`runtime_dump.py:150`）
- `gameDirectory` 必须等于 `mc_server_dir`（启动脚本先 `cd`），否则文件写到别处

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
- `_load_runtime_dumps`：`.json` 优先、截断 warning、0 字节 warning、`_` 前缀、非 dump JSON

## 7. Wrong vs Correct

- **Wrong**：`[rd] FAIL ... unknown ...` 先按 Unknown 处理 → 重试 16 次、重复执行 dump
  **Correct**：先判 `DONE_PREFIX`/`FAIL_PREFIX`，再判 Unknown（`runtime_dump.py:238`）
- **Wrong**：超时后重发命令（旧 `TRANSIENT_RCON_ERRORS` 吞掉 `TimeoutError`）→ dump 执行两次
  **Correct**：`asyncio.TimeoutError` 前置捕获、只重连不重发（`rcon_client.py:105`）
- **Wrong**：把 `.json` 当 `.jsonl` 逐行读 → 整文件 JSON 永远解析失败
  **Correct**：按后缀分流（`kb/builder.py:148-164`）
