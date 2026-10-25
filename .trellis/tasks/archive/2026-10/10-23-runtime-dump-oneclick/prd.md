# 运行时 dump 一键化：插件触发 researchdump 并自动收集合并

关联：GitHub issue #4（fanjinchi/astrbot_plugin_mc_manager）

## Goal

把目前 README 里的四步手工 dump 流程压缩为一条插件指令 `/mc_kb_dump`：插件自动完成脚本部署（按需）、RCON 触发、结果收集（KubeJS 直写 `<kind>.json`）、知识库重建，并回执统计。研究、实现、线上实测验证在本任务内一体完成。

## 已确认的决策（grill 结论 + 四轮评审修订；证据锚点见 `research/01-rcon-trigger.md`）

1. **范围**：研究+实现+验证一体；研究结论记到本任务 `research/`（本轮已落 `research/01-rcon-trigger.md`，实测后在文件末尾补章节）。
2. **环境**：线上服 `/home/guigui/mc/CTI0.46/`（CTI 0.46 整合包，**MC 1.19.2** + KubeJS 1902.6.2-build.73，RCON localhost:25575 已启用，`max-tick-time=60000`）作实测环境；前提是不影响服务器运行。**首次实测先在 /tmp 复制服或单类别探针上预演**（记录耗时/体积/响应内容），再上线上低峰跑全量。
3. **输出通道（方案 B）**：`runtime_dump.js` 用 KubeJS 官方允许的 **`JsonIO` 全局绑定**直写 `<server>/runtime_dump/<kind>.json`（`java.io`/`java.nio` 被 KubeJS 类过滤器禁止，已静态确证）。**不写任何标记文件**（`_done.json`/`_loaded.json` 均不采用）。**不走日志 ##RD## 提取**（原方案 A 废弃），`assets/extract_runtime_dump.py` 随之退役（文件删除，git 历史可查）。`kb/builder.py` 增加 `<kind>.json` 读取支持（需同时改四处：后缀过滤、`stem` 切片、整文件 `entries` 解析、`_` 前缀跳过；jsonl 保留兼容），端到端无转写层。手工降级流程为**四步**：`mkdir -p <server>/runtime_dump` → 拷 JS 到 `kubejs/server_scripts/` 并重启服务器或执行 `/reload` → **OP（权限 2 级）或服务器控制台**执行 `/researchdump` → `/mc_kb_rebuild`（JsonIO 不建父目录；不 reload 新脚本不会注册命令）。
4. **触发与完成判定（本轮简化）**：**一次 RCON 调用同时完成就绪确认、触发和完成判定**——服务端 RCON 会阻塞到命令执行结束并把命令反馈回传（`DedicatedServer.m_7261_` 清空缓冲→`executeIfPossible` 内 `join` 等待→返回 `RconConsoleSource.getCommandResponse()`；反馈由 `sendSystemMessage` 累加，已静态确证，见 research 第 1 节）。JS 结束时把统计作为反馈发回：`[rd] DONE {"counts":{...},"failed":[],"duration_ms":N}`；整体失败发 `[rd] FAIL <原因>`。插件按响应分支：
   - 含 `[rd] DONE` → 解析统计，进入重建；
   - 含 `[rd] FAIL` → 回执失败原因；
   - 含 `Unknown` → 命令尚未注册（`/reload` 未完成）→ sleep 2s 重试（最多 15 次 / 30s）；超时回执诊断，**不再二次 `/reload`**；
   - `错误: 无法连接...` → RCON 不可用，立即回执 + 手工四步；
   - `错误: 命令响应超时...` → dump 未在 180s 内结束（watchdog 风险），回执失败并提示查服务器日志；
   - 其它/空响应 → 回执「命令已执行但未收到 DONE 标记」，提示查看 `logs/kubejs/server.log` 与产物文件。
5. **RCON 超时修复（评审 P0-1）**：aiomcrcon `send_cmd` 默认 2s 硬超时，且 `TimeoutError`（OSError 子类）会命中断线重连重发 → 双执行。修法：`execute_async` 加可选 `timeout` 参数（`None` 时**不传参**给 `send_cmd`，保持现有调用方 2s 默认；dump 用 180s、reload 用 120s）；超时单独捕获 → 重连但**绝不重发**，返回带「超时」字样的错误文案。
6. **RCON 发送串行化（评审新增）**：长命令期间 MC 聊天回复/QQ 喊话的 `tellraw` 会抢同一连接造成响应错位/半包，进而命中 TRANSIENT 重连重发（最坏双 dump）。`execute_async` 的 `send_cmd` 段加发送锁（`asyncio.Lock`，dump 与其它调用共享）；`test_connection_async` 也走同一把锁。
7. **MC 版本兼容（评审 P0-2）**：线上为 1.19.2，`BuiltInRegistries`（1.19.3+）不存在。JS 改为双版本兼容：优先 `net.minecraft.core.registries.BuiltInRegistries`，fallback `net.minecraft.core.Registry`；修正脚本头注释。
8. **脚本部署**：部署前比对 `kubejs/server_scripts/runtime_dump.js` 与插件 assets 内容，缺失/不一致才写入并 RCON `/reload`（timeout=120s）；一致则跳过（防版本漂移、避免不必要卡顿）。`/reload` 的 RCON 响应**不代表重载完成**（1.19.2 `ReloadCommand` 调用 `reloadResources` 后立即返回，静态确证）→ 新命令是否可用由第 4 条触发调用里的 `Unknown` 重试确认；若 `/reload` 响应为 `错误: 无法连接...`，直接回执 RCON 不可用 + 手工四步。部署阶段由插件**在最前面**预创建 `<server>/runtime_dump/`（失败回执带 `mkdir -p` 命令）。
9. **重建**：触发成功后自动接 `kb.rebuild`（`asyncio.to_thread`），回执「dump 条数 + 重建结果」。
10. **保护**：指令受 `admin_ids` 控制（**注意：`admin_ids` 为空时任何人可用**，与其它指令一致，PRD 不再宣称「管理员专属」）；单飞锁防并发（插件级单例，main `async with` 持有）；本次长时间调用唯一超时 180s；失败回执具体原因。
11. **部分失败可见（评审 P1-1）**：JS 每类独立 try/catch，失败类别写入 DONE 反馈的 `failed` 列表；**某类 0 条/失败时不写该类别的文件**（open 之前失败时旧文件保留）。注意：`JsonIO.write` 是 truncate 写，写到一半失败/崩服会留下截断文件——builder 侧对单个 `.json` 解析失败只跳过该文件并记 warning，不影响整次重建。
12. **watchdog 防护（评审 P1-2）**：dump 同步跑在服务器主线程，RCON 调用会一直阻塞到命令结束（180s 只是兜底）。**复制服全量实测**：27,643 条、`duration_ms` 295ms、产物约 6.2MB（item 4.01MB / block 1.86MB / entity 150KB / fluid 144KB）、0 failed → watchdog 余量极大（阈值 60s）。验收阈值仍为单次 `duration_ms < 30s` 且无 watchdog 告警。`/reload`（仅首次部署/脚本变更）原型实测约 3.4s tick 积压；实测挑低峰/空服、避开 FTB Backups 的整点/半点。
13. **降级**：无 `kubejs/` 目录、RCON 不可用等场景明确提示并给手工四步（含 `mkdir`、重启或 `/reload`、OP/控制台执行 `/researchdump`）。
14. **收尾**：README 改为一键流程为主、手工四步为降级；`research/` 留存结论；验收后关闭 issue #4（评论说明方案 B 取代 ##RD##、issue 研究问题 2 的前提已随聊天互通重构消失、extract 脚本退役为有意偏离）。

## Requirements

- 新增指令 `/mc_kb_dump`（受 `admin_ids` 控制，默认空=所有人），全流程不阻塞 AstrBot 事件循环。
- `runtime_dump.py` 新模块：logger 沿用 `kb/__init__.py` 的 ImportError fallback（可脱离 AstrBot 独立测试）。
- RCON 失败判定用 `错误:` 前缀（error-handling.md 约定），禁止 `if not result`。
- 前置检查包含 `self.kb is None` 分支（照搬 `mc_kb_rebuild`）。
- JS 命令加 `.requires(src => src.hasPermission(2))`，防普通玩家执行刷屏（RCON 4 级不受影响）。
- JS 结束时必须通过 `ctx.source.sendSystemMessage(...)` 回传单行统计（`[rd] DONE {...}` 或 `[rd] FAIL ...`），长度 < 4KB（RCON 单包上限）。
- dump 输出写 `<mc_server_dir>/runtime_dump/<kind>.json`（`_load_runtime_dumps` 扩展支持；条目 schema `{kind,id,tkey,resolved,stack}` 冻结，与 builder 现有 `_dump_id` 逻辑对齐；`_` 前缀文件跳过）。
- builder 的 `.json` 读取对半写/损坏文件单独容错（跳过该文件 + warning），不能拖垮整次重建。
- 损坏/截断文件的 warning 必须接入 `builder.rebuild` 的 `warnings`（`_load_runtime_dumps` 当前签名只有 `(server_dir, data_dir, rows)`，需新增 `warnings` 参数或返回并合并），最终在 `/mc_kb_status` 可见。
- `kb/commands.py` 读取的 `runtime_dump/commands.jsonl` 通道不受影响：`.json` 读取器只处理含 `entries` 的对象，其它 JSON 跳过。
- 失败场景（无 KubeJS / RCON 失败 / 超时 / 部分类别失败 / reload 后命令仍不可用 / 未收到 DONE 标记）均有明确回执，静默失败不允许。

## Acceptance Criteria

- [ ] 线上服实测：一条 `/mc_kb_dump` 完成「触发 → 收集 `<server>/runtime_dump/<kind>.json` → rebuild」，回执显示各类别条数与重建结果。
- [ ] 首次执行自动完成脚本部署（含一次 `/reload`），首次触发遇 `Unknown` 自动退避重试并成功；二次执行脚本内容一致时不再 reload 直接成功。
- [ ] 无 KubeJS / RCON 不可用场景回执明确的**手工四步**（含 `mkdir`、重启/`/reload`、OP/控制台执行 `/researchdump`）降级步骤（用 `/tmp` 夹具目录与停机 RCON 验证，不改造线上 `kubejs/`）。
- [ ] dump 期间 AstrBot 事件循环不阻塞，单飞锁与 180s RCON 超时生效；单次 `duration_ms < 30s` 且服务器无 watchdog 告警/未断线（实测耗时与产物体积记录在案）。
- [ ] 部分类别失败时回执可见，且对应类别旧 dump 文件不被空覆写；截断文件只导致该类被跳过并 warning（`/mc_kb_status` 可见；用 `/tmp` 夹具验证）。
- [ ] README 更新；`research/` 留存 RCON 触发与版本兼容实测结论；issue #4 关闭。

## Out of Scope

- 自写服务端 mod/数据包替代 KubeJS（方案 B 已解决输出稳定性，无需额外 mod）。
- 不同机部署的自动化（配置层面要求同机 `mc_server_dir`，只给手工文案）。
- 定时/周期性自动 dump。
- JS 分片/节流执行（仅当实测接近 watchdog 阈值时再立项）。
