# P6 真机 AC 验收（RCON help 回退采集）

> 日期：2026-10-28。只使用 `/home/guigui/mc/rcon-help-probe/` 下的隔离副本；原实例 `CTI0.46`、`Farming` 全程未被写入
> （server.properties SHA-256 与 mtime 和 MANIFEST 记录一致，见 §10）。

## 1. 环境与启动方式

| 副本 | 版本 | server-port / rcon.port | KubeJS | Java | 用途 |
|---|---|---|---|---|---|
| CTI-nokubejs | 1.19.2 Forge 43.4.12 | 21341 / 25581 | 已移除 | 17 | AC1 闭环、AC2/AC3/AC4/AC5 |
| CTI-kubejs | 1.19.2 Forge 43.4.12 | 21340 / 25580 | 保留 | 17 | AC6 结构化导出 vs RCON 对照 |
| Farming-kubejs | 1.20.1 Forge 47.4.20 | 21342 / 25582 | 保留 | **21** | AC2 多包证据（1.20.1）、AC6 对照 |
| Farming-minimal | 1.20.1 Forge 47.4.20 | 21344 / 25584 | 无（新建最小包） | **21** | AC1 的 1.20.1 fallback 验收 |

- Farming-minimal 按 implement.md §0.3 新建：新目录 + rsync 副本的 libraries/启动脚本（排除 world/logs/mods/config 等），
  `mods/` 只放 `[葡园酒香] letsdo-vinery-forge-1.4.41.jar`、`[前置]architectury-9.2.14-forge.jar`、`letsdo-API-forge-1.2.15-forge.jar`，新世界 `minimal_world`。
  （首次启动因 rsync 的 `mods/` 排除规则连带丢了 `libraries/cpw/mods`，补回后正常；这是操作失误，不影响产品代码。）
- 1.19.2 启动：`cd <副本> && java @user_jvm_args.txt @libraries/net/minecraftforge/forge/1.19.2-43.4.12/unix_args.txt nogui`
- 1.20.1 启动：`cd <副本> && JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 PATH=$JAVA_HOME/bin:$PATH java @user_jvm_args.txt @libraries/net/minecraftforge/forge/1.20.1-47.4.20/unix_args.txt nogui`
- 全部副本 `rcon.password=guigui`、`server-ip=127.0.0.1`；扫描期间除本插件外没有其它 RCON 写入者。

## 2. 验收方法（重要限制）

用 `MCManagerPlugin.__new__` + 真实 `MinecraftRCON` + 真实 `KnowledgeBase`（临时数据目录）在独立进程调用**生产入口方法**
`cmd_kb_rcon_scan` 的完整 async generator（权限 → KubeJS 门槛 → 单飞 → 真实两阶段扫描 → `validate_snapshot` →
`publish_snapshot` → 回执）。**没有**经过 AstrBot 的消息分发/平台适配层（未重启线上 AstrBot，避免干扰用户运行中的机器人）；
权限/门槛/单飞/发布/回执都是生产代码路径，但属于"入口方法级"而非"机器人消息级"验收。协议故障穷举仍以 `tests/test_rcon_help.py`
的 fake server 为准；真机验证正常链路 + 可在线构造的失败（鉴权失败、端口不通、取消）。

## 3. AC1 无 KubeJS 闭环

### 3.1 1.19.2（CTI-nokubejs）

入口回执原文：

```
✓ RCON help 命令树已发布
根命令 179 个，用法/别名 474 条
请求 362 次（2N+4），片 365，字节 50926，耗时 1636ms
发布路径：/tmp/p6-cti-h7no395z/runtime_dump/commands.json
边界：一级子命令可还原，更深分支是 help 压缩语法；纯根命令可能未收录，targeted 空响应不代表裸根不可执行
```

- `kb.enabled=False`（物品库未配 `mc_server_dir`），跨机/无本机目录仍可发布与查询。
- 快照 `/tmp/p6-cti-h7no395z/runtime_dump/commands.json`，SHA-256 `8b50e86790fe0de1c3be8654c361929ef795749ecedd125414b19fb3d49db88d`，`producer=rcon`，`count=474`。
- 根帮助发现 N=179，发布条目覆盖 161 个根（其余为 targeted 空响应/纯根，按设计不发布）。
- 查询 `search_mc_commands("advancement")` 返回真实 usage + `producer=rcon` 降级提示 + "纯根命令可能未收录"：

```
找到 3 个匹配「advancement」的命令：
- /advancement — 授予/撤销进度成就（游戏操作，来源未知，权限未知）
  语法：
    · advancement grant <targets> (only|from|until|through|everything)
    · advancement revoke <targets> (only|from|until|through|everything)
- /gamerule — 游戏规则，常用：keepInventory死亡不掉落 doDaylightCycle昼夜更替 mobGriefing生物破坏 doFireTick火焰蔓延 naturalRegeneration自然回血（世界，来源未知，权限未知）
  语法：
    · gamerule announceAdvancements [<value>]
    · gamerule coinDropPercent [<value>]
    · gamerule commandBlockOutput [<value>]
    · gamerule disableElytraMovementCheck [<value>]
    · gamerule disableRaids [<value>]
    · gamerule doBetterServerSleep [<value>]
    · gamerule doDaylightCycle [<value>]
    · gamerule doEntityDrops [<value>]
    （另有 32 条用法，可用更精确的关键词）
- /haveadv — 运行时命令（来源未知，权限未知）
  语法：
    · haveadv <advancement>
注：运行时语法来自 RCON help，根命令与一级子命令可还原，更深分支是压缩语法（(a|b)、[x]、...），不能当作完整参数；实际执行还受 RCON 可见性限制。纯根命令可能未收录（targeted 空响应不代表裸根不可执行）。
```

- 扫描后同一客户端普通命令拿到自己的响应，无 help 残留：`list` → `There are 0 of a max of 20 players online:`。

### 3.2 1.20.1（Farming-minimal，无 KubeJS）

```
✓ RCON help 命令树已发布
根命令 82 个，用法/别名 199 条
请求 168 次（2N+4），片 169，字节 23292，耗时 1519ms
发布路径：/tmp/p6-minimal-3y6w0c53/runtime_dump/commands.json
边界：一级子命令可还原，更深分支是 help 压缩语法；纯根命令可能未收录，targeted 空响应不代表裸根不可执行
```

- `wine age <years>` / `wine info` 与实时 dispatcher 一致：`['wine age <years>', 'wine info']`；`search_mc_commands("wine")` 返回这两条 usage。
- 快照 SHA-256 `29403cb1b1771a0096401db84e9ea19726230cf8f0fbba4fa5937b68190f11dd`，`count=199`，N=82，请求 168 次 = `2*82+4`。
- 扫描后 `list` 正常：`There are 0 of a max of 20 players online:`。

## 4. AC2 传输完整（双版本）

对生产代码打点（monkeypatch `rcon_help._send/_read_frame` 记录每笔请求的 id/片数/时序），每个副本各跑一次完整扫描：

| 副本 | 交换数 = N+2 | 正式请求 | 根 help 片数 / 字节 | B 全部在 A 首包后 | 多包响应数 | 帧数账目 |
|---|---|---|---|---|---|---|
| CTI-nokubejs（1.19.2） | 181 | 362 | 2 / 6892 | 是 | 2 | 通过（1 认证帧 + A 片 + B 片 = report.packets） |
| Farming-kubejs（1.20.1） | 185 | 370 | 3 / 10889 | 是 | 3 | 通过 |

- 两版本根 help 都超过 Java 单包 4096 字符（6892 / 10889 bytes），只有收到 B 才结束；扫描后普通 `list` 均正常。
- Farming-minimal 根 help 仅 3227 bytes（单包），因此 1.20.1 的多包证据按 implement.md 允许取 Farming-kubejs（长响应/另一副本）；
  Farming-minimal 的传输同样经过完整扫描与帧数账目校验（169 帧 = 168 请求 + 1 认证，见 AC1）。

## 5. AC3 解析与提示

- 真实 redirect：`chunks -> ftbchunks`、`dimstorage -> dimtablet`、`execute as <targets> -> execute`（快照拆成 `syntax` + `redirect`）。
- 压缩语法保留：`['advancement grant <targets> (only|from|until|through|everything)', 'advancement revoke <targets> (only|from|until|through|everything)', 'aether eternal_day (set|query)']`。
- 纯根边界：`['chunks', 'dimstorage', 'sophisticatedbackpacks', 'tell', 'tf']` 等只来自显式 redirect；根级 `/foo`、空 targeted 未生成普通 `syntax="foo"`。
- 查询同时显示"一级子命令可还原 / 深分支压缩 / 纯根可能未收录 / targeted 空响应不代表裸根不可执行"（见 AC1 原文）。

## 6. AC4 失败关闭

离线（fake server，96 个协议/入口用例）覆盖 EOF、截断 length/body、坏终止字节、错/未知 id、B 缺失、尾随包、旧 id 迟到、
交换/总超时、片/字节/根数预算、首末根集合不一致、空 entries、坏 jar 注入。真机补充：

- 错误密码：回执 `❌ RCON help 扫描失败（阶段：auth）`，旧快照 SHA-256 仍为 `8b50e86790fe0de1…`。
- RCON 端口不通：回执 `阶段：connect`，旧快照 hash 不变。
- 取消活动扫描：`cancelled=True`、`_rcon_scan_lock.locked()=False`、`_rcon_scan_task` 清空；随后普通 `list` 正常。
- 按设计不承诺：同根集 reload 热替换、任意中间内容片删除、外部 RCON 写入者并发，只记录为限制。

## 7. AC5 能力检测与管理入口（入口级真机）

| 场景 | 结果 |
|---|---|
| 非管理员 | 回执 `权限不足：用户 intruder 不在管理员列表中`；`rcon._client is None`（零 RCON 连接） |
| 重复调用 | 回执 `⏳ 已有 RCON help 扫描在进行中，请等它结束（结果会单独回执）`；零 RCON |
| 本机 KubeJS 证据 | 回执 `❌ 本机 mods/ 检测到 KubeJS（kubejs-mekanism-1902.1.5-build.20.jar）…`；零 RCON |
| 扫描失败 | 回执含阶段/auth、失败根、进度、请求/片/字节/耗时、旧快照保留 |
| 卸载/重载取消 | `terminate()` 取消真实扫描，socket 关闭、锁释放、普通命令恢复 |
| 进度回执 | 开始回执含"暂停其它 RCON 写入者""跨机=管理员确认 fallback 环境" |

限制：未经过 AstrBot 消息分发层（见 §2）；`help help` / `help 1` / 不存在命令探针在 P0 已实测，本次未重复分页探针。

## 8. AC6 分环境差分与性能

同一副本、同一 dispatcher：先 `researchdump`（生产 `assets/runtime_dump.js`，内容与已部署一致、未触发 reload），紧接着 RCON A/B 扫描：

| 副本 | 结构化导出（KubeJS） | RCON 扫描 | 共同根 | 仅 KubeJS 有 | 仅 RCON 有 | 请求数 / 片数 / 耗时 |
|---|---|---|---|---|---|---|
| CTI-kubejs（1.19.2） | 2061 条 / 188 根 | 493 条 / 164 根 | 164 | 24（纯根/空 targeted） | 0 | 370 / 373 / 1641ms |
| Farming-kubejs（1.20.1） | 2248 条 / 193 根 | 667 条 / 162 根 | 162 | 31 | 0 | 370 / 376 / 1671ms |

- 一级 usage 总量：CTI KJS 2000 vs RCON 493（压缩 107 条）；
  Farming KJS 2177 vs RCON 667（压缩 121 条）。
- `roots_only_kjs` 例子：CTI `['ars-pathing', 'back', 'cca_api', 'collective', 'ftbultimine', 'hat', 'kickme', 'lcclaims']`；Farming `['ambrosiareset', 'back', 'cca_api', 'corgilib', 'coshat', 'dback', 'delhome', 'fixdimensions']` —— 均为纯根/无可发现一级 usage，符合设计。
- 具体命令（Farming）：`wine` 的 KJS 与 RCON 一级 usage 完全一致：['wine age <years>', 'wine info']；
  更深路径只在 KJS 侧（如 `advancement grant <targets> from <advancement>` vs RCON `advancement grant <targets> (only|from|until|through|everything)`）。
- `roots_only_rcon` 为空，说明 RCON 没有伪造根；根集合差异来自 `getAllUsage(..., false)` 包含纯根/深层路径。

## 9. AC7 文档

- `README.md`「无 KubeJS 环境的命令树（RCON help 回退）」：入口、管理员确认、暂停其它写入者、`2N+4`、尾随窗口、纯根/深分支边界、失败与取消。
- `.trellis/spec/backend/runtime-dump.md` §3.1.2：跨层契约（传输/锁/解析/发布/生命周期/预算）。
- `.trellis/spec/backend/` 的 directory-structure / logging-guidelines / quality-guidelines 已同步模块落点、日志面、测试与验证命令。

## 10. 收尾状态与残余限制

- 验收后已停止全部副本服务器；原实例 `CTI0.46` 仍在运行且未被触碰。副本目录保留为证据；`Farming-minimal` 是本次新建目录，
  按父任务阶段 9 在父任务归档后随整个 probe 根清理。
- 临时发布目录在 `/tmp/p6-*`（不进仓库）；证据原文与脚本保留在 `/tmp/p6_*.py`、`/tmp/p6-*.json`，关键值已抄入本文。
- 原实例保护：`CTI0.46/server.properties` SHA-256 `6c86326d…fdd46c05`、mtime `2026-10-26 21:56:24`；
  `Farming/server.properties` SHA-256 `fa5d9e17…45d4dd9`、mtime `2026-10-26 18:05:05`，与 MANIFEST 一致。
- 未做/不可保证：机器人消息级入口（AstrBot 分发层）验证、外部 RCON 写入者并发安全、同根集 reload 热替换、任意中间删片检测、
  远程网络 RTT/完整墙钟（本次为回环）。
