# 执行计划：运行时 dump 一键化（方案 B / JsonIO 版，命令反馈作完成信号）

## 前置

- [x] 加载 `trellis-before-dev`，读 `.trellis/spec/backend/index.md` 及相关规范（重点：error-handling.md 的 `错误:` 前缀约定、directory-structure.md、quality-guidelines.md）
- [x] 读 `research/01-rcon-trigger.md`（本题证据锚点；区分「已静态确证」与「待实测」两类结论）

## 研究与预演（先于编码）

- [x] 0. `research/01-rcon-trigger.md` 本轮已落盘（jar 探针 + 顺序分析 + RCON 完成信号证据 + 规模证据）；实施时只补「实测章节」
- [x] 0b. 原型预演已完成（research 第 8 节）：JsonIO 写盘、RCON 回传 `[rd] DONE/PROBE`、reload 后 Unknown 窗口（~5s）、reload 代价（~3.4s tick 积压）均已实测；**复制服全量也已完成**（27,643 条 / 295ms / 约 6.2MB / 0 failed / id 全部可解析，见 research 8.2）。线上真机验收已于 2026-10-25 11:32 在 3 人在线时完成（见 research 8.3）

## 实现（顺序执行）

- [x] 1. `rcon_client.py`：`execute_async` 加可选 `timeout`（`None` 时**不传参**给 `send_cmd`，保持 2s 默认）；`asyncio.TimeoutError` 在 TRANSIENT 之前单独捕获（重连不重发，返回带「超时」字样的错误文案）；新增 `self._send_lock` 并在 `send_cmd` 段串行化（`test_connection_async` 的 `send_cmd("list")` 也走同一把锁）；现有调用方零改动
- [x] 2. `assets/runtime_dump.js` 重写 v2：双版本 Registry 兼容（BuiltInRegistries → Registry fallback，Mojmap 成员名靠 Rhino 重映射）；`JsonIO.write('runtime_dump/<kind>.json', {...})` 字符串直传直写（TypeWrapper 自动转 Path/JsonObject；**禁止用 `Utils.getPath`**——全局绑定的 UtilsWrapper 无此方法）；0 条/失败类别不写；**结束时 `ctx.source.sendSystemMessage(Component.literal('[rd] DONE ' + JSON.stringify({counts, failed, duration_ms})))`，整体异常发 `[rd] FAIL <原因>`（单行 < 4KB）**；无 `_done.json`/`_loaded.json`、无顶层写盘；`.requires(src => src.hasPermission(2))`；头注释改**四步**用法（mkdir → 拷文件并重启/`/reload` → OP/控制台 `/researchdump` → /mc_kb_rebuild）；条目 schema `{kind,id,tkey,resolved,stack}` 冻结
- [x] 3. `kb/builder.py`：`_load_runtime_dumps` 增加 `.json` 读取——同时认 `.json`/`.jsonl`（stem 分别 `fn[:-5]`/`fn[:-6]`）、跳过 `_` 前缀、`.json` 解析 `{kind,count,entries}`、**每个文件独立 try/except**（损坏/截断→warning+跳过，不能拖垮整次 rebuild；`_load_runtime_dumps` 需加 `warnings` 参数或返回并合并到 `rebuild` 的 warnings）、同名类别 `.json` 优先于 `.jsonl`、不含 `entries` 的 JSON 跳过（不动 `kb/commands.py` 的 commands.jsonl 通道）；jsonl 兼容保留
- [x] 4. 新增 `runtime_dump.py`：RuntimeDumpRunner（预建 `<server>/runtime_dump/`、内容比对懒部署、`/reload` 后**一次触发调用 + `Unknown` 退避重试（2s×15，共 30s）**、解析 `[rd] DONE/FAIL` 反馈、回执编排）；纯函数 `_parse_dump_summary`/`_response_says_unknown`/`_rcon_error_kind`/`_script_deploy_needed`；错误分支：无法连接→回执+手工四步，响应超时→失败提示查日志，DONE/FAIL→对应处理，其它→「未收到 DONE 标记」；单飞锁为插件级单例，由 main 用 `async with` 持有（Runner 不释放）；唯一长时间调用超时 180s（`/reload` 120s）；logger 用 ImportError fallback
- [x] 5. `main.py` 新增 `/mc_kb_dump` 指令（照搬 `mc_kb_rebuild` 模式，含 `self.kb is None` 检查）；`__init__` 建 `self._dump_lock = asyncio.Lock()`，指令里用 `async with` 包住 Runner；文案避免「仅管理员」（`admin_ids` 空=所有人）
- [x] 6. `kb/query.py:124-126`：`/mc_kb_status` 提示改为「用 `/mc_kb_dump` 生成 `runtime_dump/*.json` 后重建」（2 行）
- [x] 7. 本地静态验证 + 单测：
  - `python3 -m compileall -q main.py rcon_client.py runtime_dump.py kb/builder.py`（与 quality-guidelines spec 口径一致）
  - 临时脚本单测：`_parse_dump_summary`（DONE 正常/缺字段/非法 JSON）、`_response_says_unknown`、`_rcon_error_kind`（连接失败/响应超时/其它）、`_script_deploy_needed`、超时分支（重连不重发）、发送锁串行化（含 `test_connection_async`）、builder 的 `.json` 读取/截断跳过/json 优先/非 dump JSON 跳过（验证后删除临时脚本）

## 线上实测（用户已授权，前提不影响服务器；先预演再线上，挑低峰、避开 FTB Backups 的 :00/:30）

- [x] 8. 首次 `/mc_kb_dump`：验证 预建目录 → 懒部署（写脚本+reload）→ **首次触发 `Unknown` 自动退避、成功拿到 `[rd] DONE` 统计** → rebuild 全链路；实测：27,643 条 / 首次 1.9s、二次 322ms / 6.2MB / 0 failed；产物与复制服逐字节一致；线上本次未出现 Unknown（reload 响应返回时命令表已就绪）→ 见 research 8.3
- [x] 9. 二次 `/mc_kb_dump`：实测命令序列只有 `['researchdump']`（无 reload）、322ms 成功
- [x] 10. 失败路径抽查：截断真实 `item.json` → builder 跳过+warning、同目录 `block.json` 仍合并 9,729 条（线上实测）；RCON 停机/超时/FAIL/未收到 DONE/Unknown 耗尽 → 假 RCON 覆盖全部回执分支；单飞锁与权限分支为代码审查（未做真实并发/非管理员触发）
- [x] 11. `research/01-rcon-trigger.md` 补「实测章节」：RCON 触发 KubeJS 命令实测、`/reload` 后首次 Unknown 次数、命令反馈文本实测、各阶段耗时/体积、版本兼容结论
- [x] 12. 线上无 watchdog（日志 0 次）、无玩家断线；仅首次 reload 时一次 `Can't keep up 3508ms/70 ticks`；事后 TPS 20 / tick 29.5ms

## 收尾

- [x] 13. 删除 `assets/extract_runtime_dump.py`（线上实测通过后再删；README 同步改）
- [x] 14. README：一键流程为主、手工**四步**为降级；检查点（**行号以实施时为准，按内容定位**）：物品知识库功能列表（`/mc_kb_rebuild` 附近，加 `/mc_kb_dump` 一行）、`AstrBot/data/plugin_data/mc_manager/` 目录名（应为 `astrbot_plugin_mc_manager`）、结构图 `runtime_dump/*.jsonl`（改 `*.json`）、「运行时 dump」整节（四步流程含重启/`/reload` 与 OP 说明 + 产物名 `.json`；**跨机拷贝段的两处 `data/plugin_data/mc_manager` 都要改**，并把「同名取 mtime 新」改成「`.json` 优先，旧 `.jsonl` 可删」）、文末更新日志（**新增** v1.5.0 条目，历史条目不改）；`metadata.yaml` 升 1.5.0
- [x] 15. spec 同步：`directory-structure.md` 根模块区（`main.py` 之后）补 `runtime_dump.py`、`assets/` 区删 `extract_runtime_dump.py`（当前约 `:53`），`:14-20` 依赖图与 `:76-85` 新功能表各补一行、`quality-guidelines.md` compileall 命令、`error-handling.md` Pattern A 代码块与行号（改完 `execute_async` 后行号会漂移；**当前行号是准的**，不是「旧行号」）
- [x] 16. `trellis-check` 质量门禁 + `code-review`（子代理）：审查结论无 P0/P1；7 条 P2 已逐条核实并修复（generic 错误归类、登录超时文案、FAIL 含 unknown 误重试、Unknown 回执补恢复步骤、0 字节文件 warning、升级首跑重试一次、文档/无用 import）
- [ ] 17. 验收全过后关闭 GitHub issue #4（评论附实测结论；说明方案 B 取代 `##RD##`、issue 研究问题 2 的前提已随聊天互通重构消失、extract 脚本退役为有意偏离）
- [ ] 18. 提醒用户 commit（不擅自提交）

## 回滚点

- 步骤 1-7 插件侧为新增+可选参数+builder 增量，git 还原即回滚；`assets/extract_runtime_dump.py` 可从 git 历史恢复
- 步骤 8-12 只向服务器写 `kubejs/server_scripts/runtime_dump.js` 与 `runtime_dump/`，均可手工删除；**已注册的 `/researchdump` 会保留到下次 `/reload` 或重启**
- `kb/query.py` 文案与 `metadata.yaml` 版本可单独回退

## 验收对应

- AC1（一条指令全链路）→ 步骤 8
- AC2（首次部署 + Unknown 退避 + 二次不 reload）→ 步骤 8/9
- AC3（降级文案 + 夹具验证）→ 步骤 10 + 步骤 14 手工四步
- AC4（不阻塞、单飞锁、180s 超时、`duration_ms < 30s`、无 watchdog）→ 步骤 8/10/12
- AC5（部分失败可见、旧文件不被空覆写、截断只跳过该类）→ 步骤 10 夹具
- AC6（README、research、关闭 issue）→ 步骤 11/13/14/17
