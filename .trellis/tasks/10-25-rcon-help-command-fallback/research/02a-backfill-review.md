# 02a 回填后独立评审（开工门禁）

- 日期：2026-10-28
- 范围：只评审规划产物与 P0 证据；未实现代码、未改产品代码、未改 `prd/design/implement`、未改 `02-rcon-ab-probe.md` 与原始 `p0-*.json`。唯一写入文件为本报告。
- 方法：逐文件读取；用临时 Python 脚本重算三份原始 JSON（N、2N+4、根 help 片/字符/字节、空包、A/B id、RTT、并发/锁/隔离字段）；实际执行计划中的验证命令的基线部分（unittest、compileall、node、ruff、main 导入）。
- 结论先行：**当前不能直接勾选开工门禁；不存在 P0。** 核心设计自洽、P0 关键数字基本可靠；但有 2 个开工前必须补的 P1，以及 1 个 P6/AC1 前必须定案的 P1。补齐后可开工，P1–P5 的实现路径没有设计阻塞。

## 1. 可开工性判断

| 结论项 | 判断 |
|---|---|
| 是否存在 P0（设计死路/无法实现） | 否 |
| 当前能否直接开工 | **否**；先补 P1-1（验证门 ruff 不可按原样执行）与 P1-2（KubeJS 残留目录会误拒扫描） |
| 补 P1-1/P1-2 后能否开工 P1–P5 | **可以**；代码落点、共享锁、validate/publish 复用均已核对可行 |
| P6/AC1 能否当前收口 | **不能**；P1-3 需先定案（Farming no-KubeJS 起服与 AC1 口径） |
| 最该盯的风险 | ①整次扫描持有 `_send_lock` 可达 300s；②P6 Farming no-KubeJS 环境/AC1；③KubeJS 门槛误判；④ruff 验证门 |

## 2. P0 数字核对（原始 JSON 重算）

三份 JSON 的字段一致（`phases.scan.samples` 为 dict；`root_count_N`、`budget_requests_2Nplus4`、`initial_help/final_help`、`root_set_consistent`）。重算结果：

| 项目 | CTI-kubejs | CTI-nokubejs | Farming-kubejs | 与 `02` 表 |
|---|---|---|---|---|
| N（`len(samples)` / `root_count_N` / `roots_by_newline`） | 183 / 183 / 183 | 179 / 179 / 179 | 182 / 182 / 182 | 一致（02:54） |
| `2N+4` / `budget_requests_2Nplus4` | 370 | 362 | 368 | 一致（02:55） |
| 首/末根 help 片数 | 2 / 2 | 2 / 2 | 3 / 3 | 一致（02:57） |
| 首/末根 help 字符 | 7122 / 7122 | 6892 / 6892 | 10875 / 10875 | 一致（02:58） |
| 首/末根 help 字节 | 7142 / 7142 | 6912 / 6912 | 10905 / 10905 | 一致（02:58） |
| 根 help 每包字节 | 4106, 3036 | 4106, 2806 | 4106, 4106, 2693 | 一致（02:59） |
| `help execute` 字符/片数 | 425 / 1 | 425 / 1 | 593 / 1 | 一致（02:60） |
| 空 targeted（`a_empty=true`，完整 samples） | 30 | 28 | 31 | 一致（02:61；原始 `empty_packet_roots` 只存前 20） |
| `no_packet_roots` | 0 | 0 | 0 | 一致（02:77） |
| 空包 payload | 10 字节 / 0 字符（stop/seed/reload/xp 等） | 同左 | 同左 | 一致（02:77） |
| 首/末根集合 | 一致（diff []） | 一致 | 一致 | 一致（02:64） |
| targeted 交换循环耗时 | 0.02s | 0.03s | 0.08s | 一致（02:63，字段 `scan_seconds`） |
| 最后 B 后尾随 | 5s 无包（`trailing=[]`） | 同左 | 同左 | 一致（02:65） |
| `help help` | 18 字符 | 18 | 18 | 一致（02:120） |
| 双客户端同 ID 重复 | 5/5 轮，单侧 2 份完整响应 | 5/5 轮，其中 1 轮翻转 | 5/5 轮 | 一致（02:102） |
| 共享锁 | 0.44s；释放后 list 正确 | 同左 | 同左 | 一致（02:99） |
| 扫描后普通命令隔离 | `looks_like_list=true` | 同左 | 同左 | 一致（02:66） |

**不一致/需修正的具体项：**

1. **`02` 说 targeted 样本全是单包，但 Farming 的 `gamerule` 是 2 包。**
   - 字段：`p0-farming-kubejs.json` → `phases.scan.samples.gamerule.a_packet_count = 2`、`a_chars = 6633`、`body_head` 以 `/gamerule announceAdvancements ...` 开头；其余 181 个 targeted 为 1 包，CTI 两份为 183/179 全部 1 包。
   - 与 `02:69`“targeted 样本（`help <root>`）在本轮都是单包”直接冲突。
   - 影响：这是**正面的多包 targeted 证据**，应补进 P0 表并用于 P6 AC2；否则 P6 可能只拿根 help 证明多包，测试也可能误以为 targeted 单包。
2. **`02:57` 的“实际 A/B 请求数 370/368/362”是公式值，不是观测值。**
   - 字段：`phases.scan.actual_requests` 由探针按 `2*(len(targets)+2)` 计算（`probe_rcon_ab.py:521`），不是计数器。
   - 同一条扫描 socket 还在 targeted 与末次 help 之间做了 `empty_targeted_detail` 额外交换（`probe_rcon_ab.py:490-508`）；末次 help 的 id 证明这些请求确实发出：CTI-kubejs 末次 `a_id=500378`（正式段到 500370 结束，多 10 个请求）、CTI-nokubejs `500368`（多 8）、Farming `500374`（多 8）。
   - 影响：正式扫描口径 370/362/368 没算错，但“实际”二字会误导 P6 AC6 的实测计数；P6 必须明确把 empty-detail/能力探针排除在 `2N+4` 之外。
3. **`02:62` RTT 行的“首个交换 41.1ms/40.8ms”标注不准确。**
   - CTI-kubejs：initial `rtt_b_ms=40.73`，final `41.08`；02 写的 41.1 是 **final**，不是首个。
   - Farming：initial 39.92、final 40.22；02 写的 40.8 是某个 **targeted 样本的最大值**（`samples` max 40.79），不是首个。
   - 另：`implement.md:73` 用“平均/最大”（0.45/0.66/0.46）与 02 的“中位/最大”不同；数值本身可复现（含首末、负值钳制后的均值 0.4474/0.6572/0.4519），但建议统一口径/注明统计方法。
4. **`probe_rcon_ab.py` 的 `roots_by_slash` 不是有效的无换行根发现证据。**
   - 原始 JSON：`root_parse.roots_by_slash` = 333 / 327 / 341，而 N 用的是 `roots_by_newline` = 183 / 179 / 182。
   - `split_roots()` 的 slash 分支（`probe_rcon_ab.py:205-217`）在空白处也会把 usage 片段记成“根”，所以 333 不是 333 个根；它不能证明“无换行时按 / 切分即可发现 183 个根”。无换行路径实际由 P2 离线夹具覆盖（`implement.md:118`），P0 不应把它写成已验证。

**P0 数字总评**：N、2N+4、根 help 片/字符/字节、空包数、根集合、execute、锁/隔离/并发均与原始 JSON 一致；只有上述 4 处表述/口径需要修正，未发现伪造或数量级错误。

## 3. 设计自洽与可实现性

### 3.1 A/B 状态机与 `_send_lock`

- 现实现：`rcon_client.py:46` 的 `_send_lock` 在 `execute_async`（`rcon_client.py:93`）和 `test_connection_async`（`rcon_client.py:141`）中覆盖发送；设计让 `scan_help_commands()` 在**同一条锁**内完成整次扫描，符合现有互斥边界。
- `execute_async` 在拿锁前调用 `_ensure_connection()`（`rcon_client.py:92`）；扫描持锁期间普通命令可以完成连接建立，但发送会等待，不会插入 A/B 之间。设计 §3.1 已说明，未发现冲突。
- `_ensure_connection` 用独立的 `_lock`，`close()` 也不拿 `_send_lock`；扫描失败/取消时关闭扫描 socket、释放 `_send_lock`，不会重连/重发普通命令。设计与现有代码可衔接。
- 没有发现“扫描复用 aiomcrcon client”或“扫描嵌套调用 `execute_async`”的死锁路径；`rcon_help.py` 作为 stdlib-only 低层模块也不依赖 AstrBot，符合分层。

**但有一个现实影响**：整次扫描持有 `_send_lock` 最长 300s（`design.md:168`），期间插件自身的聊天出栈、LLM 工具、`/mc_kb_dump` 的 RCON 全排队；`execute_async` 等锁没有超时。设计 §3.1 承认“只能等待”，但 PRD/R8 没把它写成管理员可见的可用性影响。见 P2-6。

### 3.2 `validate_snapshot()` / `publish_snapshot()` 是否真能复用

- `kb/commands.py:40` 已把 `rcon` 列入 `SNAPSHOT_PRODUCERS`；`validate_snapshot()`（`kb/commands.py:98`）接受 `name/syntax/source/level/redirect`，允许 `source="unknown"`、`level=None`、`redirect` 字符串；`publish_snapshot()`（`kb/commands.py:156`）用同目录 `mkstemp` + `os.replace()`，失败清理临时文件、不删旧快照。
- `validate_snapshot` 要求 `syntax.split(" ")[0] == name`；设计中的 targeted 行去掉前导 `/` 后以根名开头、redirect 拆出，正好满足；根 redirect `{name:"xp", syntax:"xp", redirect:"experience"}` 也满足。**不需要改 schema。**
- `main.py` 的 `self.kb.data_dir` 即使 `kb.enabled == False` 也已初始化（`main.py:96-103`、`kb/__init__.py:39-50`），跨机 `mc_server_dir=""` 仍可发布/查询；设计 §2.1 结论成立。
- 结论：复用链可行，没有发现必须改 schema 的点。唯一需要实现时注意的是：RCON parser 必须先把 `-> target` 拆到 `redirect`、把根级压缩行排除，再交给 `validate_snapshot`；否则 `syntax.split` 校验会失败。

### 3.3 纯根、深层压缩、空 targeted、尾随窗口

- 纯根规则（targeted 空不生成 `syntax=="foo"`、根级 `/foo` 不补造、显式 redirect 例外）在 `prd.md:29`、`design.md:140-147`、`implement.md:118-121` 三处口径一致。
- 尾随窗口只用于最后 B、静默到期算完成、窗口内额外包失败，三处一致（`prd.md:28/49`、`design.md:98/114`）。
- 失败关闭清单（EOF/截断/错 id/B 缺失/超时/超限/根集合不一致/空 entries）一致（`prd.md:30/51`、`design.md:103-114`、`implement.md:94-96`）。
- 未发现设计与现有 `execute_async` 语义冲突；扫描不自动重试、失败保留旧快照，与 `publish_snapshot` 行为一致。

## 4. P1–P7 可执行性

### 4.1 文件与路径

- 计划中的 `rcon_help.py`、`tests/test_rcon_help.py` 为新增；`rcon_client.py`、`main.py`、`kb/commands.py`、`tests/test_commands.py` 均存在；`runtime_dump.py`、`kb/__init__.py` 不改，符合最小落点。
- 解释器 `/home/guigui/code/AstrBot/.venv/bin/python` 存在（Python 3.12.13）；`tests/` 存在（`test_commands.py`、`test_runtime_dump.py`、`test_dump_script.py`）；`node`、`assets/runtime_dump.js`、`ruff`（`/home/guigui/.local/bin/ruff`）均存在。**没有“解释器路径不存在”的问题。**
- 基线：`python -m unittest discover -s tests -v` 47 个用例通过；`node --check assets/runtime_dump.js` 通过；`compileall` 可用。

### 4.2 验证命令中真正会失败的部分

**P1-1（开工前必须补）：`ruff format/check` 门不可按原样执行。**
- 位置：`implement.md:101-104`（P1）、`126-131`（P2）、`152-158`（P3）、`183-189`（P4）、`197-204`（P5）、`241-246`（P7）。
- 实测（显式文件，继承 AstrBot 根 `pyproject.toml` 的 `line-length=88` 和 `F/W/E/ASYNC/C4/Q/I/UP`）：
  - `ruff check rcon_client.py` = 20 errors（12 W293、3 E722、2 UP045、I001、Q000、W292）；
  - `ruff check main.py` = 142 errors（136 W293 + I001/F401/F541/Q002）；
  - `ruff check kb/commands.py` = 32 errors（26 UP031、6 UP045）；
  - `ruff check tests/test_commands.py` = 4 UP031；
  - `ruff format --check main.py rcon_client.py` = “would reformat”两个文件；P4/P5 的 `ruff format main.py` 会给 900 行文件带来大量空白/尾逗号改动，和 `implement.md:208`“没有全仓 reformat”以及 `.trellis/spec/backend/quality-guidelines.md:11-14`“只在新增/改动文件跑、不清零既有 UP031/UP045”直接冲突。
  - 在当前 workspace-write 下，`ruff` 还会因尝试写 `/home/guigui/code/AstrBot/.ruff_cache` 而直接失败（`Read-only file system`）；需要 `RUFF_CACHE_DIR=/tmp/...` 或 `--no-cache`。
- 影响：P1/P4/P5 的 gate 会红；实现者要么忽略 lint gate，要么整文件 reformat，产生与功能无关的大 diff。
- 建议：把 gate 改成与 spec 一致的“只查本次新增文件 + 对比既有告警类型”（例如 `ruff check --select F,E9` 或基线 diff），并明确 `RUFF_CACHE_DIR`；不要对 `main.py`/`rcon_client.py` 跑 `ruff format`。

**P1-2（开工前必须补）：KubeJS 残留目录会误拒扫描。**
- 位置：`design.md:183`（`kubejs/` 目录或 `mods/` 中 KubeJS jar 均作为“已安装证据”拒绝），`implement.md:44`（P0 自己承认“移走脚本目录以防环境门槛把遗留目录误判为已安装”）。
- 现实场景：用户删除 KubeJS jar（或换整合包）但 `kubejs/` 脚本目录仍在——这正是要跑 fallback 的环境；入口会以“已安装 KubeJS”拒绝，AC1 无法完成。P0 为了测试专门移走了目录，等于承认生产门槛会误判。
- 建议：硬证据只认 `mods/` 中 KubeJS mod（jar 元数据/mod id）+ 可读取的 jar；目录只作为警告或辅助提示，不作为拒绝条件；跨机时明确“本机目录不对应远程”时不拒绝。

**P2-5（建议）：P4 入口级测试的 `main.py` 导入/实例化方式未写。**
- `main.py:14-20` 使用相对导入，直接 `import main` 会 `ImportError: attempted relative import with no known parent package`（已实测）；`tests/test_commands.py:13` 的 `sys.path.insert(plugin_root); from kb import commands` 模式不能直接套到 `main`。需以 `astrbot_plugin_mc_manager.main` 加载（父目录入 `sys.path`）或 `importlib`。
- `main.py:96` 的 `StarTools.get_data_dir` 在 `__init__` 中调用；入口测试若不 patch 到临时目录，可能写真实 `plugin_data`，违背“临时目录隔离”。
- 影响：P4/AC5 的“入口级测试”容易写不出来或变成只测纯函数；建议在 P4 明确导入方式和临时 data_dir fixture。

**P2-6（建议）：整次扫描持有 `_send_lock` 最长 300s 的可用性影响没有入口级提示。**
- `rcon_client.py:46`、`design.md:56/168`；扫描期间普通命令、聊天出栈、工具调用都排队，且 `execute_async` 等锁无超时；远程 RCON 若 RTT 较高，370 次串行交换可能触顶 300s（`design.md:166/168`），扫描失败关闭（安全但不产出快照）。
- 影响：管理员在活跃服上跑扫描会导致插件自身 MC 消息/命令明显卡顿；应在入口回执/README 写明“扫描期间本插件 RCON 命令排队，建议维护窗口执行”，并在 P6 实测远程 RTT/完整墙钟。

**P2-7（建议）：Farming 的 Java 21 启动条件没有落到可复现命令。**
- `02:18/22` 明确 Farming 必须 Java 21、默认 `java`(17) 会 `UnsupportedClassVersionError`；但副本 `run.sh` 仍是裸 `java`，`user_jvm_args.txt` 只有 heap/proxy，MANIFEST 没有 `JAVA_HOME`/启动命令。本机默认 `java -version` 是 17。
- 影响：P6 直接 `./run.sh` 起 Farming 会失败；应在 MANIFEST/P6 记录 `JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64`（或 zulu-21）并复述完整启动命令。

**P2-8（建议）：Farming no-KubeJS 的 MANIFEST 与实际手术不一致。**
- `02:30` 说启动报错后又剔除 `ftb-chunks-online-loading`、`greenhouse`；实际 `mods/[农场物语-核心]core-1.0.9.jar` 现在只剩 12 个内嵌 jar，`probe-disabled-mods/surgery-report.json` 记录了第二次重打包；但 `MANIFEST.md` 仍写“Farming-nokubejs：无（初始清单已覆盖）”和“剩余内嵌 jar: 14 个（原 18 个）”。
- 影响：P6 回滚/复现会漏恢复两个内嵌 mod；Start gate 第 7 项“回滚清单已有记录”并不完全成立。建议以 surgery-report 为准更新 MANIFEST，并记录两次 repack 的 hash。

### 4.3 回滚点

- P1–P5 的回滚点具体且正确（删除新增文件/方法、按阶段回退、不删除旧快照）；P6 依赖 MANIFEST，见 P2-8；P7 文档可独立回退。未发现“回滚会删旧快照/碰原实例”的问题。

## 5. PRD/design/implement 口径冲突

总体上没有发现会改变实现的硬冲突；以下三处需要统一：

1. **能力探针与 `2N+4` 的关系**（P2）：`design.md:77` 说 A 可以是“P0 专用能力探针”，`design.md:155` 又说总请求恰为 `2N+4`；`prd.md:52` AC5 和 `implement.md:222` P6 AC5 要求真实 `help help`/`help 1`/不存在命令探针。若产品入口内跑这些探针，`2N+4` 不再是总数，且 `help 1` 返回纯文本（不以 `/` 开头）不能进 A 解析。建议明确：能力探针只在 P0/独立连接，产品扫描的 `2N+4` 不含探针，并在报告里分开统计。
2. **`02:69` 的“targeted 全单包”** 与 `design.md:163`（单 A 响应片数上限 256，多包通用）以及原始 JSON 的 `gamerule` 2 包冲突；应改为“本轮 targeted 大多单包，Farming `help gamerule` 为 2 包/6633 字符”，不改变设计。
3. **`02:84` 仍写“design 里‘目标为 root 时 redirect 为 ...’与实际不符”**，但当前 `design.md:141/144` 已改成名字形式；这是 02 对旧版设计的残留描述，会让读者误以为当前 design 仍错。建议把 02 的表述改为“旧版设计曾如此，现 design 已按实测修正”。

其余（纯根、深层压缩、空 targeted、尾随窗口、失败关闭、根集合、`2N+4`、KubeJS 主路径不自动 fallback、跨机 `kb.enabled`/`mc_server_dir`）在 PRD/design/implement/parent 之间一致，未发现互相矛盾。

## 6. P6 真机阻塞判断（Farming no-KubeJS）

**记录情况：如实记录。** `02:135` 记录了 `Item: tide:cooked_fish does not exist` 起服失败；`implement.md:216` 明确“P6 前必须清理 Tide 相关 tag/recipe 或更换测试包；这不是 P0 传输结论的失败”。Start gate/PRD 也明确 P6 未完成。**没有隐瞒。**

**但诊断和修复路径没有被证据支持：**
- `02:135` 说“Tide 鱼类物品注册放在 KubeJS（`farmingtales-kubejs-support`）里”，但：
  - `probe-disabled-mods/core-1.0.9.original.jar` 内嵌的 `farmingtales-kubejs-support-1.0.0.jar` 只有 24 个条目，扫描 class/JSON 没有 `tide`/`cooked_fish` 命中；
  - Tide 自己的 `mods/[潮汐] tide-forge-1.20.1-2.1.jar` 中 `com/li64/tide/registries/TideItems.class` 明确含 `COOKED_FISH`/`SMALL_COOKED_FISH` 等注册常量；
  - `Farming-nokubejs/logs/probe-nokubejs-3.log:1408` 的 tag 错误列出的是一整批 `tide:*` fish 缺失（不是单个 recipe），`:5499` 才是 fatal；
  - 日志还出现 `dye_depot:mint_dye` 等其它缺失引用。
- 结论：这不是“删几个 tag/recipe 就好”的小修补，至少需要先定位为什么整批 Tide 物品没有注册；按 02 的描述直接清 tag/recipe 很可能只是在追错误。**但这不是死路**：
  1. CTI-nokubejs 已能起服（P0 完成 179 根全量扫描），AC1 的 RCON 闭环可以在 CTI 上先验收；
  2. `wine age <years>`/`wine info` 来自 Vinery，不是 Tide/KubeJS；P0 的 `p0-farming-kubejs.json` `samples.wine.body_head` 已给出预期形态。用一个 1.20.1 Forge + Vinery + RCON 的最小包即可复现该浅树（或从 Farming 副本移除 Tide 并清理引用），不必修好整个整合包；
  3. 若 AC1 必须逐字绑定“Farming 副本”，则当前环境确实无法完成，需要用户/规划明确修改 AC1 或接受最小 Vinery 包作为 Farming 的替代证据。

**判断：可解的工程障碍，不是死路；但“清理 tide tag/recipe”这条具体路径未被验证，且 AC1 的“Farming”口径需要先定案。** 严重级别 P1（P6/AC1 前必须定案，不阻塞 P1–P5 实现）。

## 7. 未记录的现实风险（只列会发生的）

1. **扫描长锁/300s（P2-6）**：远程 RCON 或活跃服上，插件自身聊天/工具命令会排队；300s 是回环外推的预算，不是远程 SLA。建议入口回执显式提示“本插件 RCON 命令将排队，建议维护窗口执行”，P6 实测完整墙钟。
2. **KubeJS 残留目录误拒（P1-2）**：删除 KubeJS 后 `kubejs/` 目录常残留，入口会拒绝，恰好阻断 fallback。必须改成 jar 证据优先。
3. **默认 `admin_ids` 为空时所有人都是管理员（P2-4）**：`main.py:462-474` 的既有行为；AC5 的“非管理员零 RCON”测试如果不配置非空 `admin_ids` 就是假通过，默认部署下任何用户都能触发 300s 扫描。实现/验收时应显式配置管理员列表。
4. **P6 的启动/权限可复现性（P2-7/P2-8）**：Java 21 未落到启动命令；MANIFEST 与实际 12 个内嵌 jar 不一致；P6 还要写 `/home/guigui/mc`（插件 workspace 外），需要明确由用户/有权限会话执行，否则 agent 的 workspace-write 会拒绝。
5. **P4 入口测试（P2-5）**：`main.py` 相对导入 + `StarTools.get_data_dir` 的真实数据目录副作用，若不处理，入口测试会失败或污染真实数据。

## 8. 发现清单（按严重级别）

| 级别 | 编号 | 文件/字段 | 问题 | 现实影响 |
|---|---|---|---|---|
| P1 | P1-1 | `implement.md:101-104/126-131/152-158/183-189/197-204/241-246` | `ruff format/check` 对既有文件基线不干净（20/142/32/4 errors；main/rcon_client 会被 reformat；workspace-write 下缓存写失败） | 每个阶段 gate 红；可能诱发整文件 reformat 或忽略 lint |
| P1 | P1-2 | `design.md:183`、`implement.md:44` | 把残留 `kubejs/` 目录当作 KubeJS 已安装证据 | 删 KubeJS 留脚本的用户被拒绝，fallback 无法使用 |
| P1 | P1-3 | `02:135`、`implement.md:216` | Farming no-KubeJS 阻塞已记录，但“Tide 注册在 KubeJS”诊断不被证据支持，清 tag/recipe 方案未验证；AC1 的 Farming 口径未定 | P6/AC1 可能卡住；需定案（CTI 先验收 / 最小 Vinery 包 / 明确 AC 变更） |
| P2 | P2-1 | `02:69`；`p0-farming-kubejs.json` `samples.gamerule` | 说 targeted 全单包，实际 gamerule 2 包/6633 字符 | 漏掉正面多包 targeted 证据；P6 AC2/测试可能误设单包 |
| P2 | P2-2 | `02:57`、`implement.md:70`；`phases.scan.actual_requests` | “实际请求数”是公式值；同 socket 还有 10/8/8 个 empty-detail 请求（末次 id 可证） | AC6 的“实际 2N+4”计数口径可能错 |
| P2 | P2-3 | `02:62`、`implement.md:73` | RTT 的“首个交换”标注错（41.1 是 final，40.8 是 sample max）；两文档统计量不同 | 预算/性能结论不受影响，但证据表不精确 |
| P2 | P2-4 | `main.py:462-474`；`implement.md:173` | 空 `admin_ids` = 所有人管理员；AC5 非管理员测试可能假通过 | 默认部署任何人可触发扫描；测试无意义 |
| P2 | P2-5 | `main.py:14-20/96`；`implement.md:169` | 入口测试未说明 `main` 相对导入和临时 data_dir | P4/AC5 入口测试难落地或污染真实数据 |
| P2 | P2-6 | `rcon_client.py:46`；`design.md:56/168` | 整次扫描持锁最长 300s，普通 RCON 命令排队；远程 RTT 未测 | 活跃服上聊天/工具卡顿；远程扫描可能触顶失败 |
| P2 | P2-7 | `02:18/22`；`implement.md:216`；副本 `run.sh` | Farming 必须 Java 21，但启动命令/`JAVA_HOME` 未记录，默认 java 是 17 | P6 直接 `./run.sh` 会 UnsupportedClassVersionError |
| P2 | P2-8 | `MANIFEST.md`、`02:30`、`surgery-report.json` | MANIFEST 说 Farming 无额外移除/剩 14 个内嵌 jar，实际第二次 repack 后 12 个 | P6 回滚漏恢复 2 个内嵌 mod；复现不一致 |

> 未列：纯理论上的 B 多包、任意中间删片、同根集热替换、外部并发写等；这些已在 design/PRD 中作为不可保证边界记录，不重复挑刺。

## 9. 开工后最该盯的 2–3 个风险

1. **长锁与 300s 预算**：P1 实现时先把“整次扫描持锁 + 普通命令排队”做成可观测（入口提示、耗时/请求回执），P6 用远程或至少非回环环境测完整墙钟；否则活跃服上会表现为插件卡死。
2. **P6 Farming/AC1 环境**：不要按 02 的“清 tag/recipe”盲修；优先用 CTI-nokubejs 完成 AC1 闭环，再用最小 1.20.1 Vinery 包复现 `wine` 浅树，或在 P6 前与用户确认 AC1 的“Farming”替代证据。否则实现全做完但验收收不了口。
3. **入口环境门槛与入口测试**：KubeJS 判定必须以 jar 为准（P1-2）；P4 的 `main` 入口测试要先解决相对导入和临时 `data_dir`（P2-5），否则 AC5 的“入口级证据”会退化成底层函数测试。

## 10. 复现/验证命令（本次实际执行）

```bash
# 1) P0 数字重算：读取三份 p0-*.json，逐项打印 N/2N+4/包/字符/字节/空包/id/RTT/并发
/home/guigui/code/AstrBot/.venv/bin/python /tmp/recompute_p0.py   # 临时脚本，未入库

# 2) 基线
/home/guigui/code/AstrBot/.venv/bin/python -m unittest discover -s tests -v   # 47 tests OK
node --check assets/runtime_dump.js                                          # OK

# 3) ruff（按计划原样）
ruff format --check main.py rcon_client.py kb/commands.py tests/test_commands.py
ruff check main.py rcon_client.py kb/commands.py tests/test_commands.py
# -> format: main.py/rcon_client.py would reformat
# -> check: 142/20/32/4 errors；且 workspace-write 下 .ruff_cache 只读失败
```

**最终结论：核心设计可用，P0 证据可信度足够；当前文档因 P1-1/P1-2 不能直接勾选开工门禁，补齐后可以开工。P1-3 不影响 P1–P5 启动，但必须在 P6/AC1 前定案。**
