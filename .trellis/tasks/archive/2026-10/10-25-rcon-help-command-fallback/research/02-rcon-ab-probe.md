# P0 真机 A/B 与资源实测证据

- 日期：2026-10-27
- 范围：只做 P0 探针与环境准备；未改产品代码、未发布命令快照、未执行任何有状态 MC 命令。
- 结论先行：**A 首包后 B 的状态机在多包/空包/尾随/锁/隔离上全部按预期工作；同时实测到两个必须写进设计的约束**——
  (1) `aiomcrcon` 单包读取会把 10k+ 字符的 help 截断到 4096 字符**并污染后续普通命令**；
  (2) **两个 RCON 客户端并发时，其中一个连接会收到双份完整响应**（同一 request id，6 包 / 21750 字符）。
  这两条支持“独立低层 socket + 共享 `_send_lock` + 扫描期间无其他 RCON 写入者”的设计前提。

## 1. 环境矩阵

隔离根：`/home/guigui/mc/rcon-help-probe/`（整体删除即回滚；原实例全程只读）。

| 副本 | 源 | 版本 | Java | server-port | rcon.port | heap | KubeJS | 起服结果 |
|---|---|---|---|---|---|---|---|---|
| CTI-kubejs | /home/guigui/mc/CTI0.46 | 1.19.2 Forge 43.4.12 | zulu-17 | 21340 | 25580 | -Xmx10G | 保留 | ✅ Done (39.3s) |
| CTI-nokubejs | 同上 | 同上 | zulu-17 | 21341 | 25581 | -Xmx10G | 移除 + 依赖清理 | ✅ Done (45.2s) |
| Farming-kubejs | /home/guigui/mc/Farming | 1.20.1 Forge 47.4.20 | java-21 | 21342 | 25582 | -Xmx8G | 保留 | ✅ Done (16.1s) |
| Farming-nokubejs | 同上 | 同上 | java-21 | 21343 | 25583 | -Xmx8G | 移除 + 依赖清理 | ❌ 见 §6 |

- 复制方式：`rsync -a` 排除 `world*/ backups/ logs/ crash-reports/ runtime_dump/ modernfix/ *.lock`；不复制原世界，`level-name=probe_world` 新世界；`server-ip=127.0.0.1`、`enable-query=false`。
- **Java 版本是必须项**：Farming 的 TabList 用 class 65（Java 21）编译，默认 `java`(17) 直接 `UnsupportedClassVersionError`；CTI 用 17 正常。
- 启动期联网会让起服卡死：CTI 的 Citadel 在 `setup` 里同步拉 GitHub，本机出网不通时主线程卡在 `Net.connect0`。副本统一加
  `-Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=9 -Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=9` 让下载立即失败后继续。
- 原实例保护证据：复制前后 `server.properties` SHA-256 一致（CTI0.46 `6c86326d…d46c05`、Farming `fa5d9e17…4d4dd9`），原实例日志/世界未被写入。
- 完整清单与回滚说明：`/home/guigui/mc/rcon-help-probe/MANIFEST.md`；创建脚本 `probe_setup.sh`，jar 手术脚本 `probe_patch_nokubejs.py`（均在本目录）。

### no-KubeJS 副本的移除清单
- CTI：kubejs-forge、rhino、kubejs_botania、kubejs-create、kubejsdelight、kubejs-immersive-engineering、kubejs-mekanism、kubejspowah、kubejs-thermal、`kubejs/` 脚本目录；**启动报错后追加** kjsindustrialforegoing、lootjs、ponderjs；**另需**剔除 `cti-1.2.2.jar` 里 7 个 biome JSON 对 `kubejs:*` placed_feature 的引用（否则 datapack 加载即 `Unbound values in registry` 失败）。
- Farming：kubejsadditions、kubejs-forge、[kubejs]lootjs、[犀牛]rhino、[农场物语-魔法木桶]magic_barrel、bakery_addon、selling_bin_stack_upgrade_compat；`[农场物语-核心]core-1.0.9.jar` 内含 jar-in-jar，剔除了 4 个要求 kubejs 的内嵌 mod（kubejs-support、large-aging-barrel-fix、placeable-consumables、optimizer）并同步 metadata.json；启动报错后继续剔除 ftb-chunks-online-loading、greenhouse。

## 2. 探针方法

脚本：`probe_rcon_ab.py`（stdlib-only，自实现 RCON framing；只发只读命令 `help` / `help <root>` / `help help` / `help 1` / 未知命令 / `list`）。

- **受控交换**：发 A（`help ...`）→ 必须等到 `id=A` 首包（空包也算）→ 才发短随机未知命令 B → 继续收 A → 收到 `id=B` 判完成 → 其后统计尾随窗口。
- **正式扫描**：初始根 help + 每个根一个 targeted + 末次根 help，每次一个 B，共 `2(N+2)=2N+4` 个请求；整次扫描 request id 不复用。
- **负面试验**：独立 socket 上不发 A 首包、直接连写 A+B，记录真实表现后关闭该 socket。
- **隔离与锁**：扫描 socket 关闭后用新连接发 `list`，确认没有 help 残留；再用插件现有 `MinecraftRCON._send_lock` 复现“扫描期间普通命令排队”。
- **并发探针**：两个独立连接同时发 `help`，各自读到自己连接静默为止，记录 id 与字符数。

命令：

```bash
/home/guigui/code/AstrBot/.venv/bin/python probe_rcon_ab.py \
  --copy /home/guigui/mc/rcon-help-probe/Farming-kubejs \
  --out p0-farming-kubejs.json --scan
```

## 3. P0.3 实测预算表

| 字段 | CTI-kubejs (1.19.2) | Farming-kubejs (1.20.1) | CTI-nokubejs |
|---|---|---|---|
| 根数 N | **183** | **182** | **179** |
| 预算请求数 `2N+4` | 370 | 368 | 362 |
| 正式扫描 A/B 请求数（等于 `2N+4` 公式值；同一 socket 的 empty-detail 探针另计 +10/+8/+8） | 370 | 368 | 362 |
| 根 help 片数 | 2 | 3 | 2 |
| 根 help 字符 / 字节 | 7122 / 7142 | 10875 / 10905 | 6892 / 6912 |
| 根 help 每包字节 | 4106, 3036 | 4106, 4106, 2693 | 4106, 2806 |
| `help execute` 字符 | 425（单包） | 593（单包） | 425（单包） |
| 空 targeted 包（完整 samples 重算） | 30 个根；原摘要仅前 20 | 31 个根；原摘要仅前 20 | 28 个根；原摘要仅前 20 |
| 首个 / 末次根 help 的 B 往返 RTT（本机回环） | 40.73ms / 41.08ms | 39.92ms / 40.22ms（样本最大 40.79ms） | 40.57ms / 40.33ms |
| targeted 交换循环耗时（本机回环） | 0.02s | 0.08s | 0.03s |
| 首尾根集合一致 | ✅ | ✅ | ✅ |
| 最后 B 后尾随窗口（5s） | 无包 | 无包 | 无包 |
| 后续普通命令隔离 | ✅ `list` 正常 | ✅ | ✅ |

- 上述 0.02/0.08/0.03s 只覆盖 **N 次 targeted 交换循环**，不含首次根 help、额外 empty-detail、末次根 help 和最后至少 5 秒尾随观察；原始 JSON 的 `scan_seconds` 也只是该循环字段，本轮未记录完整墙钟耗时，P6 必须另行采集，不能用这些值校准完整 300s 总预算。未来脚本分别输出 `targeted_loop_seconds` 和包含上述阶段的 `wall_clock_seconds`。RTT 只代表本机回环，时间戳精度 1ms，因此出现取整噪声；真实网络 RTT 也必须在 P6 实测。
- targeted 样本（`help <root>`）绝大多数是单包；**Farming 的 `help gamerule` 实测 2 包 / 6633 字符**（`samples.gamerule.a_packet_count=2`），是先前表格漏掉的正面 targeted 多包证据。根 help 必然多包，接收逻辑不能只读一包。

## 4. 关键机制验证

### 4.1 多包与 4096 分片
根 help 在 1.19.2 是 2 包、1.20.1 是 3 包；每包 payload 固定在 4096 字节边界（帧 4106 字节），末包为余量。**必须收到 B 才能确定 A 收完**，不能靠“读一包就返回”。

### 4.2 合法空包
`help stop` / `help seed` / `help reload` 等根返回 **10 字节 payload 的空包**（id=A、type=0、body 为空），随后 B 正常到达。直接重算三份原始 JSON 的完整 `phases.scan.samples`，`a_empty=true` 数量为：CTI-kubejs 30、Farming-kubejs 31、CTI-nokubejs 28；原始 `empty_packet_roots` 仅保存前 20 个摘要，不能当总数。三组 `no_packet_roots` 均为 0，即本环境不存在“完全没有包”的情况。
CTI 额外证据：`KubeJS 动态命令 researchdump` 在根 help 里出现 `/researchdump`，targeted 是空包 → **纯根命令的正确形态**，不能从根级 `/foo` 反推可执行 usage。

### 4.3 redirect 实测形态（与 design 文案有偏差）
- 根级：`/xp -> experience`。
- targeted：`/execute as <targets> -> execute`。
- 压缩记号仍在 syntax 里：`/execute run ...`、`(block|score|…) `。
**结论**：redirect 归一按 `-> <target>` 处理即可。实测 root 目标是 `-> execute` 这种**名字形式**，`...` 只作为压缩占位出现在 usage 尾部；旧 design 的“目标为 root 时 redirect 为 `...`”文案已按本结论修正，当前 design 不再保留该写法。P2 解析器与测试夹具按实测形态写。

### 4.4 立即连写 A+B（禁止序列）
- Farming：4 包，顺序 `A,A,A,B`，chunks `4110/4110/2790`；CTI：3 包 `A,A,B`，chunks `4110/3040/93`；均无断连、无错 id。
- 单次试验里服务端是串行处理两条命令的，但这**不能当作可依赖的安全行为**：它无法区分“A 是否已收完”，也无法暴露重复投递（见 §4.7）。仍按 design 执行“A 首包后 B”。

### 4.5 `aiomcrcon` 单包截断与后续命令污染（实测）
- 插件现有 `execute_async("help")` 返回 **4096 字符**（完整为 7122 / 10875），`looks_truncated=true`。
- 紧接着在同一连接 `execute_async("list")`：
  - Farming 返回残留 help 片段：`ateRespawn|doInsomnia|doLimitedCrafting|...`（不是 list 结果）；
  - CTI-kubejs 返回 `.../kubejs (help|custom_command|...)`（明确残留，`contaminated=true`）。
  - CTI-nokubejs 也返回非 list 的残留帮助文本；旧脚本的 `contaminated=false` 是判定假阴性，不能据此否认为污染。
**结论**：长 help 不能用 `execute_async` 承载；必须独立低层 socket，且失败后关闭 socket，不能把残片留给后续命令。

### 4.6 共享 `_send_lock`
持锁执行一次完整 A/B 交换 0.44s，期间并发 `execute_async("list")` 在锁释放后 **0.6–0.8ms** 返回，且内容正确（`There are 0 of a max of 20 players online`）。锁语义符合 design。

### 4.7 双客户端并发：单连接收到双份响应
两个独立连接同时发 `help`，各自 request id 不串（没收到对方的 id），但**其中一个连接收到两份完整响应**：3 包/10875 字符 → 6 包/21750 字符（CTI-kubejs：7122→14244；CTI-nokubejs：6892→13784）。每轮哪一侧被重复不固定。
- 影响：请求/响应不再是 1:1；如果扫描期间有外部写入者，B 判据之后还可能来一整份重复响应，会被误判为尾随包或被当成下一轮 A。
- 与 PRD R8 一致：**扫描期间必须没有其他 RCON 写入者**，本插件的 `_send_lock` 只约束自身；该现象只记录形态，不宣称机制已定位。

### 4.8 原始字段限制与修正解释

本次保留 `p0-*.json` 原始文件，不回写其字段。阅读时注意：

- 旧 `list_after_plugin_help.contaminated` 只检查响应前 40 个字符是否含 `/`，因此对 Farming、CTI-nokubejs 出现假阴性；`looks_like_list=false` 与原始响应头才是本次结论依据。探针脚本已改为按 list 响应形态判断。
- 旧 `exchange().anomalies` 会把首包后、B 前的正常 A 包记为“时间早于 B 发送时间”；这些不是协议错误。脚本已删除该误报，首包前非 A、未知 ID 仍按异常处理；B 后尾随单独记录，供人工判定，不写入 anomalies、不使交换失败。产品扫描器的尾随失败关闭属于后续 P1。
- 旧 `concurrent_clients.anomalies=[]` 只表示没有收到对方 ID，不表示没有同 ID 重复响应。脚本新增同 ID 包数、字符数和按完整根 help 长度估算的响应份数；原始 JSON 的重复结论仍以包数/字符数对照为准。
- 旧 RTT 使用毫秒舍入时间戳，个别值出现微小负数；这不是负网络延迟。脚本对未来记录做零值钳制，旧数据只用于近似回环参考，不作为远程 SLA。
- 旧 targeted 样本未统一保存 `a_bytes`，报告不估算缺失字节；脚本已补记该字段。根 help 的字符/字节和包序列完整保留。

### 4.9 能力探针
| 命令 | 结果 |
|---|---|
| `help help` | 18 字符：`/help [<command>]` |
| `help 1` | 44 字符：`Unknown command or insufficient permissions`（不是分页） |
| `help <不存在命令>` | 同上 44 字符；只作探针，不解析固定英文文案 |
| `list`（扫描 socket 关闭后） | `There are 0 of a max of 20 players online: ` |

## 5. 对设计/实施的影响（评审用）

1. **空包判据成立**：A 首包用“收到同 id 包（含 0 字符）”即可，不需要额外超时兜底；本环境没有“完全无包”分支。
2. **redirect 归一按 `-> name`**：实测 root 目标是名字形式，`...` 只在 usage 尾部作压缩占位；旧 design 文案已修正，P2 解析器/夹具按实测形态写。
3. **多包阈值**：根 help 在 7k–11k 字符、2–3 包；targeted 样本单包。设计里“>4096 必须多包接收”得到独立证据。
4. **尾随窗口**：最后 B 后 5s 无包；结合 4.7 的重复投递，窗口不宜过短，建议实现内部预算/常量 `trailing_window ≥ 1.5s`，不新增用户配置；这只是本次回环观测校准，不是绝对完整性保证。
5. **并发前提必须显著提示**：4.7 说明外部写入者会破坏 1:1 判据，管理员回执/README 要写清楚“扫描期间暂停其他 RCON 客户端”。
6. **Java/网络两个环境坑要写进 P6 验收前置**：1.20.1 必须 Java 21；启动期联网卡死要用本地拒连代理兜底（只影响隔离副本）。

## 6. 未完成 / 阻塞项

- **Farming-nokubejs 未能起服**：移除 KubeJS 后 datapack 加载失败 `Item: tide:cooked_fish does not exist`；继续排查还遇到第二次 repack 后的启动失败。**归因订正（2026-10-28 复核）**：原记录称“Tide 鱼类物品注册在 `farmingtales-kubejs-support`”，实测该内嵌 jar（从 `core-1.0.9.jar` 的 `META-INF/jarjar/` 取出）里 `tide` 与 `cooked_fish` 字符串计数均为 0，而 Tide 自身 jar 含 162 处 `cooked_fish` 引用，因此该归因不成立，缺物品的真实原因未定位。
- **环境方案调整（2026-10-28 用户决定）**：Farming no-KubeJS 不再复用 Farming 副本，改用**最小 1.20.1 Forge + Vinery 包**（独立目录、无 KubeJS、Java 21、独立 RCON 端口）做 fallback 验收，以复现 `wine age <years>` / `wine info`；这是 P6 环境方案调整，不是 P0 传输结论的阻塞。Farming-kubejs 副本仍用于 AC6 分环境差分。
- 双客户端“双份响应”的机制未定位（只记录形态）；一次未复现不构成并发安全证据。
- 真实网络 RTT、完整墙钟耗时、多包在真实网络下的分片行为未测（本表全是回环）；本轮只有 targeted 交换循环耗时，P6 必须补采完整墙钟。
- 扫描期间“无其他写入者”是运行前提，插件无法自证；P6 验收要记录当时的写入者状态。

## 7. 证据文件

| 文件 | 内容 |
|---|---|
| `probe_rcon_ab.py` | 探针脚本（A/B 状态机、负面试验、并发、锁、截断） |
| `probe_setup.sh` | 4 个隔离副本的创建与端口/JVM 配置 |
| `probe_patch_nokubejs.py` | no-KubeJS 副本的 jar-in-jar 剔除与 `kubejs:*` worldgen 引用清理 |
| `p0-farming-kubejs.json` | Farming 1.20.1 全量扫描原始证据 |
| `p0-cti-kubejs.json` | CTI 1.19.2 全量扫描原始证据 |
| `p0-cti-nokubejs.json` | CTI 无 KubeJS 副本全量扫描原始证据 |
| `/home/guigui/mc/rcon-help-probe/MANIFEST.md` | 副本端口、JVM、移除清单、原实例保护与回滚 |

> P0 证据已回填，原始 JSON 保持不变；本轮未改产品代码、未建 products 快照、未执行 `task.py start`。P6 环境阻塞、后续实现评审和用户开工许可仍未完成。
