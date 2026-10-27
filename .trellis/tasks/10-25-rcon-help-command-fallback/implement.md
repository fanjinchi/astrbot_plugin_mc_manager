# RCON help 回退采集实施计划

> P0 真机探针已完成并回填，证据见 `research/02-rcon-ab-probe.md`；P1–P7 产品实现、P6 验收、回填后的独立评审和用户开工许可仍未完成，不得因 P0 完成而启动实现。

## Start gate（全部完成前保持 `planning`）

- [x] `design.md` 已锁定 A/B 状态机、共享 `_send_lock`、纯根证据、预算公式、入口与一致性边界。
- [x] `implement.md` 已列 P0–P7、验证命令和阶段回滚点。
- [x] CTI0.46（1.19.2）与 Farming（1.20.1）的隔离副本探针均完成，证据写入 `.trellis/tasks/10-25-rcon-help-command-fallback/research/02-rcon-ab-probe.md`。
- [x] P0 已完成禁止的立即 A+B 负面试验（本次未断连）、A 首包后 B 的正常多包/空包/id 序列、后续普通命令隔离和共享锁行为。
- [x] P0 已填真实 N、`2N+4` 请求数、片数、字符/字节、RTT、targeted 交换循环耗时，并逐项确认 design 的资源上限和最后 B 后尾随窗口；完整墙钟耗时留待 P6。
- [x] P0 已记录扫描期间无其他 RCON 写入者的运行前提；双客户端同 ID 重复响应只作故障观察，不作为并发安全证明。
- [x] 隔离副本的 KubeJS/附属 mod 处理、端口、启动命令和回滚清单已有记录；原实例未被修改。
- [ ] 回填后的独立评审和用户后续开工许可仍未完成；不得以 P0 或文档回填替代 `task.py start` 前的审批。

## P0（start 前）：双版本隔离副本与受控探针

**P0 只产出探针脚本/证据，不改产品代码，不发布命令快照。** 探针位于 `.trellis/tasks/10-25-rcon-help-command-fallback/research/probe_rcon_ab.py`，实测记录位于同目录 `02-rcon-ab-probe.md`；两者及原始 `p0-*.json` 均已产生，原始 JSON 保持不动，当前 manifest 只接入已存在证据。

### P0.1 隔离环境矩阵

| 基线 | 副本 | 用途 |
|---|---|---|
| CTI0.46 / 1.19.2 | 保留 KubeJS | A/B 探针、动态命令可见性、P6 AC6 对照 |
| CTI0.46 / 1.19.2 | 移除 KubeJS 及会缺依赖崩服的附属 mod | P6 AC1/AC2/AC4 fallback 验收 |
| Farming / 1.20.1 | 保留 KubeJS | A/B 探针、P6 AC6 对照 |
| Farming / 1.20.1 | 移除 KubeJS 及必需附属 mod | `wine` 浅树、1.20.1 fallback 验收 |

- P0 已创建并停服保留隔离副本；后续 P6 只能复用这些隔离目录或按同样规则新建，不操作原实例。原目录、启动脚本、运行状态、端口和 mods 清单已记录在 P0 证据中；Farming 副本必须沿用 Java 21 和本地拒连代理前置。
- 建议隔离根为 `/home/guigui/mc/rcon-help-probe/`。沿用归档 `verify_copy.sh` 的最小副本方式，排除世界、备份、日志和派生产物；先读取 `level-name` 并把实际世界目录加入排除项。每个目标目录必须不存在，若已存在则停止并换带时间戳的新目录，不覆盖或 `rm -rf` 复用。示例：

  ```bash
  install -d /home/guigui/mc/rcon-help-probe
  test ! -e /home/guigui/mc/rcon-help-probe/CTI-kubejs
  ionice -c3 nice -n 10 rsync -a \
    --exclude 'world/' --exclude 'world_nether/' --exclude 'world_the_end/' \
    --exclude 'backups/' --exclude 'logs/' --exclude 'crash-reports/' \
    --exclude 'runtime_dump/' --exclude '*.lock' \
    /home/guigui/mc/CTI0.46/ /home/guigui/mc/rcon-help-probe/CTI-kubejs/
  ```

  其余三个副本按上表映射源目录和目标目录，使用同样的存在性检查与排除规则；若实际世界目录不同，必须另行排除。若原服正在写入，先使用用户已有快照/停服窗口获得一致副本；不得在写入中的权威世界目录上盲目执行。
- 每个副本使用独立 server/RCON 端口和独立数据目录，启动前记录实际端口与命令。只能从副本目录启动，不能连接原实例端口。
- no-KubeJS 副本先用 `find <副本>/mods -maxdepth 1 -type f -print` 和 mod metadata 清单识别 KubeJS 及声明必需依赖的附属 mod。把**逐项确认的显式路径**移动到副本内 `probe-disabled-mods/`，同时移走该副本的 KubeJS 脚本目录以防环境门槛把遗留目录误判为已安装；不使用未经审阅的宽泛通配符删除 mod。
- 回滚以副本内移动清单逐项 `mv` 回原相对路径，并恢复副本的端口/脚本；原实例不执行这些移动。副本启动失败时先看缺失依赖日志，再补齐附属 mod 清单，不修改原服来“修复”副本。

### P0.2 传输与 help 探针

在两个版本分别执行并保存原始 length/id/type、包数字符/字节和时间线：

- [x] **禁止序列负面试验**：已在隔离副本用一次性 socket `write(A); write(B)` 立即连写并记录真实表现；本次未断连、未见错 ID，但不改变禁止连写规则，后续正常探针不复用该 socket。
- [x] **受控正常序列**：A 发送后必须观察到 `id=A` 首包才发 B；分别记录根 `help` 与 `help execute` 的实际长度和包序列，每个版本至少选择一个真实超过 4096 Java 字符的响应（优先根 help，不足时另选长 targeted help）证明 B 到达前完整收集 A。不得预设 `help execute` 必然多包，B 文本不参与解析。
- [x] **空包**：找到无可见一级子命令的终端根，记录 targeted 的真实 `id=A` 空包和随后的 `id=B`；验证空包不是读取超时，也不生成普通纯根 entry。
- [x] **id 序列与后续隔离**：记录 A/B id，探针整次扫描不复用 request id；交换结束并关闭扫描 socket 后，用现有 `execute_async("list")` 等普通命令确认响应属于该命令，无 help 残留。
- [x] **尾随窗口校准**：测量最后 B 后的有界等待、窗口内迟到包和静默结束，确定 `trailing_window` 的实测候选值及其与总预算的关系；静默到期算检查完成，不是交换超时。
- [x] **共享锁与外部写入者前提**：探针在现有 `_send_lock` 内执行完整 A/B 序列，同时发起普通 `execute_async()`；用时间线证明普通命令在锁释放前未发送、释放后得到自己的响应。记录扫描期间无其他 RCON 写入者的前提；另用第二个独立 RCON 客户端做只读竞争探针，记录共享反馈缓冲的故障形态，不能以一次未复现宣称并发安全，也不新增外部面板锁。
- [x] **help 能力与语法**：执行 `help help`、`help 1`、不存在命令和根/targeted 对照；Farming 记录 `/wine age <years>`、`/wine info`，CTI 记录 `researchdump` 动态命令。`help 1` 只作能力探针，不实现分页。
- [x] **纯根证据**：分别记录根级 `/foo`、root-only、根与子并存、empty-targeted、redirect 的真实形态；确认 RCON 生产规则不会由 `/foo` 或空 targeted 推断普通 `syntax="foo"`。
- [x] **本地化/非标准输出**：记录当前实例错误形态；解析规则只接受完整结构，不依赖固定英文错误字符串。

### P0.3 实测预算记录

`02-rcon-ab-probe.md` 每个版本至少填写下表，不能拿历史 count/root 数代替新测量：

| 字段 | CTI-kubejs 实测 | CTI-nokubejs 实测 | Farming-kubejs 实测 |
|---|---|---|---|
| 根数 N | 183 | 179 | 182 |
| 预算请求数 `2N+4` | 370 | 362 | 368 |
| 实际 A/B 请求数（正式扫描，不含独立能力探针） | 370 | 362 | 368 |
| 根 help 片数/字符/字节 | 2 / 7122 / 7142 | 2 / 6892 / 6912 | 3 / 10875 / 10905 |
| `help execute` 片数/字符/字节 | 1 / 425 / 旧样本未汇总 | 1 / 425 / 旧样本未汇总 | 1 / 593 / 旧样本未汇总 |
| 空 targeted 包序列（完整 samples 重算） | 30 个空包，A→B；原摘要前 20；无 no-packet | 28 个空包，A→B；原摘要前 20；无 no-packet | 31 个空包，A→B；原摘要前 20；无 no-packet |
| 平均/最大 RTT（回环近似） | 0.45 / 41.08ms | 0.46 / 40.57ms | 0.66 / 40.79ms |
| targeted 交换循环耗时 | 0.02s | 0.03s | 0.08s |
| 后续普通命令隔离 | 通过；关闭扫描 socket 后 list 正确 | 通过；关闭扫描 socket 后 list 正确 | 通过；关闭扫描 socket 后 list 正确 |
| 最后 B 后尾随窗口/总预算关系 | 5s 无包；候选 ≥1.5s，纳入 300s 总预算 | 5s 无包；候选 ≥1.5s，纳入 300s 总预算 | 5s 无包；候选 ≥1.5s，纳入 300s 总预算 |
| 无其他 RCON 写入者前提与竞争观察 | 已记录；同 ID 双份完整响应 | 已记录；同 ID 双份完整响应 | 已记录；同 ID 双份完整响应 |

以上 0.02/0.03/0.08s 仅是 N 次 targeted 交换循环耗时，不含首次根 help、额外 empty-detail、末次根 help 和最后至少 5 秒尾随观察；本轮未记录完整墙钟耗时，P6 复验必须采集，不能用这些值校准完整 300s 总预算。RTT 已对旧时间戳的微小舍入负值做零值钳制，仅为回环近似；旧 targeted 样本未统一保存 `a_bytes`，不估算补齐，未来探针已补记。原始 JSON 的字段限制及污染/并发判定修正见 `research/02-rcon-ab-probe.md`。

**P0 回滚点**：删除/保留临时探针证据不影响产品；关闭所有探针 socket，恢复副本配置和移动文件。任何意外连接到原实例、需要改原实例或无法证明 A/B 顺序时，停止后续阶段并回规划评审。

## P1：低层传输与离线 fake server

### 改动文件

- 新增 `rcon_help.py`：stdlib-only RCON framing、认证、A/B 状态机、预算和有界关闭。
- 修改 `rcon_client.py`：新增 `scan_help_commands()`，整次扫描持有现有 `_send_lock`；不改 `execute_async()`。
- 新增 `tests/test_rcon_help.py`：标准库 `unittest` fake server 与锁测试。

### 实施与故障用例

- fake server 断言 B 不得在 A 首包前到达；分别返回多包 A、合法空 A、忽略文本的 B，并检查整次扫描 request id 不复用。
- 覆盖 A 首包前/后 EOF、截断 length、截断 body、非法终止字节、错/未知 id、B 缺失、最后 B 后窗口内尾随包、窗口内静默成功、跨交换旧 id 迟到、交换/总超时、片数/字节超限。
- 覆盖失败后 writer 关闭、锁释放、后续普通命令不被扫描 socket 残片污染；现有 `execute_async()` 的签名和重试分支不变。
- 明确不把“中间删片但仍有合法 B”写成必能检测的测试承诺；idle-drain 只能辅助诊断，不能代替 B 判据。

### 验证

```bash
/home/guigui/code/AstrBot/.venv/bin/python -m unittest discover -s tests -p 'test_rcon_help.py' -v
/home/guigui/code/AstrBot/.venv/bin/python -m compileall -q rcon_client.py rcon_help.py tests/test_rcon_help.py
ruff format rcon_client.py rcon_help.py tests/test_rcon_help.py
ruff check rcon_client.py rcon_help.py tests/test_rcon_help.py
```

**P1 回滚点**：删除 `rcon_help.py` / `tests/test_rcon_help.py`，只回退 `rcon_client.py` 新增方法；旧快照和普通 RCON 路径不动。

## P2：smart usage 严格解析

### 改动文件

- 修改 `rcon_help.py`：根/targeted 解析、显式 redirect 归一、结构化错误报告。
- 修改 `tests/test_rcon_help.py`：纯函数夹具。

### 必测夹具

- 无换行的 `/foo a/foo b <x>`、多分支 `(a|b)`、可选组 `[x]`、深层压缩、真实 `-> target`（含 `/xp -> experience`、`/execute as <targets> -> execute`）和 usage 尾部 `...`；另设根级与 targeted 的合成裸 `->` 容错夹具（允许尾部空白，归一为 `redirect="..."`），不得把裸 `->` 当本次实测形态。
- 根级单独 `/foo`、root-only、`foo` 与 `foo bar` 并存：RCON 只保留有正向一级/redirect 证据的条目，不从根级或空 targeted 生成普通 `syntax="foo"`。
- targeted 空响应合法且产生零条普通 entry；显式根 redirect 不因空 targeted 被删除。
- 非 redirect 裸 targeted、错根前缀、根 help 空响应、混入本地化错误、自定义非预期文本、坏 UTF-8/结构均失败；B 的本地化未知命令文本不进入 A 解析。
- KubeJS `syntax == name` 的既有共享 schema/测试不改。

### 验证

```bash
/home/guigui/code/AstrBot/.venv/bin/python -m unittest discover -s tests -p 'test_rcon_help.py' -v
/home/guigui/code/AstrBot/.venv/bin/python -m compileall -q rcon_help.py tests/test_rcon_help.py
ruff format rcon_help.py tests/test_rcon_help.py
ruff check rcon_help.py tests/test_rcon_help.py
```

**P2 回滚点**：只回退解析和夹具；尚未接发布入口，旧快照不受影响。

## P3：两阶段编排、可发现一致性与原子发布

### 改动文件

- 修改 `rcon_help.py`：首次根 help → N 个 targeted → 末次根 help，汇总 `producer="rcon"` 快照与诊断 report。
- 修改 `tests/test_rcon_help.py`：编排、预算、失败关闭和共享发布测试；复用 `kb/commands.py` 的 `validate_snapshot()` / `publish_snapshot()`，不建立第二套写入逻辑。

### 必测行为

- N 个根的实际请求数恰为 `2N+4`；根数/响应/总量/超时预算均在发送或累积越界时失败。
- 根顺序变化但集合相同可继续；由确定性 fake server 注入的首尾根集合增删、末次结构异常或任一 targeted 失败均不发布，不依赖真机临场 reload 的不稳定时序。
- 同根集合下结构热替换不可由 help 原子排除，只在文档记录限制，不伪造“已检测全部 reload”的通过项。
- 全部成功后才 `validate_snapshot()` + `publish_snapshot()`；空 entries、坏 schema、count 不一致均拒绝，临时文件清理且旧快照 hash 不变。
- report 含失败根、completed/N、请求/片/字节和耗时；成功 entries 按共享规则去重稳定排序，不伪造 source/level/参数类型。

### 验证

```bash
/home/guigui/code/AstrBot/.venv/bin/python -m unittest discover -s tests -p 'test_rcon_help.py' -v
/home/guigui/code/AstrBot/.venv/bin/python -m unittest discover -s tests -p 'test_commands.py' -v
/home/guigui/code/AstrBot/.venv/bin/python -m compileall -q rcon_help.py kb/commands.py tests/test_rcon_help.py tests/test_commands.py
ruff format rcon_help.py tests/test_rcon_help.py
ruff check rcon_help.py tests/test_rcon_help.py
```

**P3 回滚点**：回退编排，删除本次临时发布目录；不得删除测试前已有旧快照。发布逻辑若需改共享 schema，停止并回父设计。

## P4：独立管理员入口与查询降级文案

### 改动文件

- 修改 `main.py`：新增 `/mc_kb_rcon_scan`、`_rcon_scan_lock`、权限/环境检查、进度和结果回执；登记活动扫描任务，并在 `terminate()` 中取消且有界等待清理。
- 修改 `kb/commands.py`：RCON 提示增加“纯根命令可能未收录”。
- 修改 `tests/test_commands.py`：两种 producer 提示、vanilla 合并和 RCON 纯根边界回归。
- 修改既有 `tests/test_rcon_help.py`：增加轻量 `main.py` 入口级测试类，不另建测试文件；覆盖权限、单飞、环境门槛、回执和取消/重载生命周期。

### 必测行为

- 权限失败不能发送 RCON，非管理员必须是零 RCON 调用；重复指令单飞，第二次调用立即回执且不排队、不发起第二轮扫描。
- 开始、成功和失败回执含设计规定的进度/失败根/耗时；扫描开始时提示暂停其他 RCON 写入者。
- `kb.enabled == False` 且 `mc_server_dir == ""` 时仍可用 `self.kb.data_dir` 发布并由 `search_mc_commands` 查询；不要求物品库或本机 mods 目录。
- 本机发现 KubeJS 正向证据时拒绝并指向 `/mc_kb_dump`，且拒绝前不发送 RCON；跨机无法证明无 KubeJS 的限制在回执/README 明示，不自动探测或新增配置。
- KubeJS 导出失败不自动调用扫描；查询和 `execute_command` 不触发扫描。
- 入口级取消/重载测试证明 `terminate()` 取消活动扫描并有界等待 writer/socket 清理后才返回，不只测试函数内部 `CancelledError`。
- RCON 提示包含深分支压缩和纯根可能未收录；KubeJS 纯根与提示不回归。

### 验证

```bash
/home/guigui/code/AstrBot/.venv/bin/python -m unittest discover -s tests -p 'test_commands.py' -v
/home/guigui/code/AstrBot/.venv/bin/python -m unittest discover -s tests -p 'test_rcon_help.py' -v
/home/guigui/code/AstrBot/.venv/bin/python -m compileall -q main.py rcon_client.py rcon_help.py kb/commands.py tests/
ruff format main.py rcon_client.py rcon_help.py kb/commands.py tests/test_commands.py tests/test_rcon_help.py
ruff check main.py rcon_client.py rcon_help.py kb/commands.py tests/test_commands.py tests/test_rcon_help.py
```

**P4 回滚点**：回退新指令和提示即可；已发布 canonical 文件仍可由旧查询读取，无需改 schema。

## P5：全量离线回归

不改功能，失败回到对应阶段修复后重跑全量：

```bash
/home/guigui/code/AstrBot/.venv/bin/python -m compileall -q main.py rcon_client.py rcon_help.py runtime_dump.py tools/ kb/ tests/
node --check assets/runtime_dump.js
/home/guigui/code/AstrBot/.venv/bin/python -m unittest discover -s tests -v
ruff format main.py rcon_client.py rcon_help.py kb/commands.py tests/test_commands.py tests/test_rcon_help.py
ruff check main.py rcon_client.py rcon_help.py kb/commands.py tests/test_commands.py tests/test_rcon_help.py
git diff --check
```

- [ ] 既有 runtime dump、命令查询、redirect、坏快照、vanilla、物品 builder 回归全部通过。
- [ ] 普通 RCON 的签名、2 秒默认、连接重试、超时不重发和空反馈语义未改。
- [ ] 没有 pytest、新运行时依赖、全仓 reformat 或仅 mock 冒充真机的结论。

**P5 回滚点**：按失败所属 P1–P4 小步回退，不以删除故障用例换取通过。

## P6：双副本真机 AC 验收

只使用 P0 建立的隔离副本；证据写入 `.trellis/tasks/10-25-rcon-help-command-fallback/research/03-live-acceptance.md`。每项记录版本、副本、命令、时间、原始回执、请求/包统计、快照路径和 SHA-256。

P0 已确认的环境前置：Farming 1.20.1 使用 Java 21，启动阶段以本地拒连代理避免 Citadel.setup 联网卡住；CTI no-KubeJS 需剔除 `cti-1.2.2.jar` 中 7 个 biome 的 `kubejs:*` worldgen 引用。Farming no-KubeJS 目前因 `tide:cooked_fish` 缺失无法起服，P6 前必须清理 Tide 相关 tag/recipe 或更换测试包；这不是 P0 传输结论的失败。

- [ ] **AC1 无 KubeJS 闭环**：no-KubeJS 副本只配置 RCON，`kb.enabled=false`/无本机 `mc_server_dir` 也完成 `/mc_kb_rcon_scan` 与查询。Farming 验证 `wine age <years>` / `wine info`；CTI 使用该副本结构化对照中实际存在的浅树模组命令，不假定 CTI 有 `wine`。
- [ ] **AC2 传输完整**：双版本各至少一个真实响应超过 4096 字符（根 help 或实测选定的长 targeted help），保存 A 首包→B→A 完→B 完的 id/片序列；`help execute` 只按实际长度记录，不用短响应冒充多包证据。扫描后普通 `list` 响应正确，不得以 idle 时间作为完整性证据。
- [ ] **AC3 解析与提示**：真机浅树、redirect/压缩形态与离线夹具一致；查询显示 `producer=rcon`、深分支压缩和纯根可能未收录。
- [ ] **AC4 可检验故障关闭**：结合 P1 fake server 的 EOF、截断、错/未知 id、B 缺失/窗口内尾随、超时、超限、静默尾随成功和旧 id 迟到，以及 P3 确定性 fake-server 的首尾根集合变化，证明旧快照 hash 不变、后续普通命令不受污染。空 targeted 不触发失败；不宣称任意中间删片、同根集热替换或外部 RCON 并发写入必然可检测。
- [ ] **AC5 能力检测与管理入口**：真实 `help help` / `help 1` / 不存在命令探针和结构化异常 fake server 均有明确回执，错误文本未写入知识库。至少一条经生产 `/mc_kb_rcon_scan` 入口验证；保留非管理员零 RCON、第二次调用不排队、KubeJS 环境拒绝、失败根/进度/耗时回执的入口级证据，并记录扫描中取消/重载后的 socket 清理。
- [ ] **AC6 分环境差分与性能**：AC1 使用 no-KubeJS 副本；AC6 则在有 KubeJS 副本对同一 dispatcher 先后取得结构化导出和 P0/测试探针的 RCON A/B 结果，比较发现根集合与一级子命令集合。记录 RCON 发现根集合与已发布根集合的区别、深层压缩原因、纯根缺失、权限可见性、实际 `2N+4` 请求数和耗时。技术对照不得绕过生产 `/mc_kb_rcon_scan` 的 KubeJS 门槛，也不能用不同时间/不同 mod 状态的快照强行判等。
- [ ] **AC7 文档素材**：保存跨机无本机目录、旧缓存保留、环境门槛和回滚的真实证据，供 P7 使用。

若同根集合 reload 前后结构变化但 help 无法发现，记录为协议限制而非失败关闭通过证据；若出现已定义可检测故障仍发布，阻断验收并回对应阶段。

**P6 回滚点**：先保留证据，再按 P0 清单恢复副本脚本、端口和移动 mod；不触碰原实例或世界数据。产品回滚按 P1–P4 反向执行，旧有效快照保留。

## P7：文档、spec 与父任务证据

### 改动文件

- `README.md`：`/mc_kb_rcon_scan`、管理员确认、扫描期间暂停其他 RCON 写入者、跨机 data_dir、A/B 扫描成本、RCON 可见性、深分支/纯根边界、尾随窗口、卸载取消、失败与缓存优先级。
- `.trellis/spec/backend/` 中实际受影响的契约：补充共享 `_send_lock`、外部写入者前提、扫描失败返回、活动任务取消和发布边界；若改索引则同步索引。只记录已验证的现实，不把限制写成理想保证。
- 父任务 `prd.md` / `design.md` / `implement.md`：填实际证据链接和验收状态，不改三个子任务结构。
- 本任务 `research/02-rcon-ab-probe.md`：P0 证据已产生并接入当前 manifests；`research/03-live-acceptance.md` 仍需 P6 完成后产生，届时再接入需要的 manifests。

### 验证

```bash
/home/guigui/code/AstrBot/.venv/bin/python -m unittest discover -s tests -v
/home/guigui/code/AstrBot/.venv/bin/python -m compileall -q main.py rcon_client.py rcon_help.py runtime_dump.py tools/ kb/ tests/
ruff check main.py rcon_client.py rcon_help.py kb/commands.py tests/test_commands.py tests/test_rcon_help.py
git diff --check
```

- [ ] README、spec、父设计和实际行为一致，尤其不恢复 N+1、idle-drain、空 targeted 回填纯根或全局原子快照承诺。
- [ ] 所有 AC 都有对应证据；未完成的实测项不勾选。
- [ ] commit/push 仍只在用户明确要求时执行。

**P7 回滚点**：文档可独立回退；任何行为与文档不一致先修文档或回产品阶段，不通过隐瞒限制收尾。
