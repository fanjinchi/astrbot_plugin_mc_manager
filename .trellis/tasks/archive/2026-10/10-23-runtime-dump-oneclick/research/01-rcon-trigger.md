# 01 - RCON 触发与 JsonIO 直写：静态核实结论

> 状态：**静态确证 + 实测**（服务端 jar 字节码、配置、启动日志、复制服与线上真机）；实测结果见 §8/§8.3。
> 目的：给 plan/design 里的结论提供可复查锚点，避免下一个人重新验证。

## 0. 环境（2026-10-24 核实）

| 项 | 值 | 证据 |
|---|---|---|
| MC / Forge | 1.19.2 / 43.4.12 | logs/2026-10-23-1.log.gz：Starting minecraft server version 1.19.2、--fml.forgeVersion, 43.4.12 |
| KubeJS | 1902.6.2-build.73 | mods/kubejs-forge-1902.6.2-build.73.jar |
| Rhino | 1902.2.3-build.284 | mods/rhino-forge-1902.2.3-build.284.jar |
| RCON | 启用，25575 | server.properties：enable-rcon=true、rcon.port=25575（ss -ltn 显示 *:25575） |
| watchdog | max-tick-time=60000 | server.properties |
| JVM | -Xmx16G -Xms16G | user_jvm_args.txt |
| 当前状态 | 服务器运行中（有玩家活动） | logs/latest.log（2026-10-24 09:32 仍有玩家下线） |
| 部署现状 | kubejs/server_scripts/runtime_dump.js 不存在、runtime_dump/ 不存在、日志无 ##RD## | ls / grep |

## 1. RCON 能否执行 KubeJS 命令、响应是否即完成信号

**结论：能，且响应就是完成信号。** 命令注册链与响应语义（全部静态确证）：

1. /reload 走 net.minecraft.server.commands.ReloadCommand：反编译（srg jar）显示 m_138235_ 先调 MinecraftServer.m_129861_(Collection)，随后对返回的 CompletableFuture 只挂 exceptionally 就 return —— **不等待、立即返回**。所以 RCON 的 /reload 响应不代表重载完成。
2. 重载时 MinecraftServer 取 ReloadableServerResources（getCommands() 返回其 Commands 字段，见 MinecraftServer.m_129892_ 字节码）。
3. ReloadableServerResources 构造器内 new Commands(...)（javap 构造器 offset 74/83）→ Forge 在 Commands 构造器里触发 RegisterCommandsEvent → KubeJS KubeJSServerEventHandler.registerCommands(...) 转发为 ServerEvents.commandRegistry → 脚本里 event.register(...) 的命令进入新 dispatcher。
4. .requires(src => src.hasPermission(2)) 在解析期过滤；RCON 源权限为 4 级，不受影响；低权限玩家会看到 "Unknown command"。
5. **RCON 响应即完成信号**：DedicatedServer.m_7261_(String) 先 RconConsoleSource.m_11512_() 清空缓冲，再 executeIfPossible(...) 后返回 RconConsoleSource.m_11513_() 响应文本；BlockableEventLoop.m_18709_（executeIfPossible）在非服务端线程时走 execute(runnable).join() → **阻塞到命令执行结束**；命令里 ctx.source.sendSystemMessage(...) 由 RconConsoleSource.m_213846_ 追加进该缓冲。**所以 JS 结束时发一行 [rd] DONE {...}，插件在同一次 RCON 调用里就能拿到完成与统计——不需要 _done.json 标记或轮询。**

- 未知命令文案（判定依据）：1.19.2 的 assets/minecraft/lang/en_us.json 有 command.unknown.command = "Unknown or incomplete command, see below for error"；RCON 源会把失败消息带回响应，所以「响应含 Unknown」可判定命令未注册。
- 已知边界：插件需区分——含 Unknown（未注册，退避重试）；[rd] DONE/FAIL（执行完成）；错误: 无法连接…（命令未发出，立即回执 + 手工四步）；错误: 命令响应超时…（未在超时内结束，按失败回执）；其它/空响应（命令可能已执行但反馈丢失，提示查日志）。

**待实测**：在 1.19.2 上第一次通过 RCON 执行自注册命令，并确认响应里能看到 [rd] DONE 行（预期可执行，需线上预演确认）。

## 2. 就绪时序（为什么第一次触发可能 Unknown）

```
/reload -> MinecraftServer.reloadResources (async)
  |- KubeJS @ModifyVariable(STORE) 包住新的 CloseableResourceManager
  |- ServerScriptManager.wrapResourceManager
  |    '- offset 182: reloadScriptManager(manager)  <- 脚本加载（早于命令表重建）
  |- ReloadableServerResources.loadResources(...)
  |    '- 构造器 offset 74/83: new Commands(...)     <- 此时新命令表才生效
  |- 资源 reload（recipes/tags/…）
  '- thenAcceptAsync: 交换 ReloadableServerResources / getCommands() 返回新表
```

**结论：脚本加载早于「命令可用」。** 任何「脚本已加载」的标记都不能证明命令能执行；而第一次触发若落在旧命令表上会立即返回 Unknown（不执行 dump），因此 design 用**触发调用本身**做就绪确认：Unknown 就 2s 退避重试（最多 15 次/30s），成功那一次即正式触发；不再使用 _loaded.json 之类的标记，也不再额外发 probe。

**待实测**：reload 后首次触发返回 Unknown 的次数/耗时（预演时记录；若 reload 常超 30s，把窗口从 30s 调到 60s）。

## 3. 输出通道：JsonIO（全部 javap 确认）

- 类过滤器：BuiltinKubeJSPlugin 字节码含 deny("java.io")、deny("java.nio")，仅 allow java.io.Closeable / java.io.Serializable / java.nio.ByteOrder。
- 全局绑定：registerBindings 把 JsonIO 绑定到 dev.latvian.mods.kubejs.util.JsonIO；Utils 绑定到 UtilsWrapper（**无 getPath**；UtilsJS 才有 getPath(String)->String 与 getPath(Object)->Path 重载陷阱）。
- 写盘签名：public static void write(java.nio.file.Path, com.google.gson.JsonObject) 是唯一重载（无 String 版）。
- 类型转换：registerTypeWrappers 为 java.nio.file.Path 与 com.google.gson.JsonObject/JsonArray/JsonElement/JsonPrimitive 注册了 wrapper；UtilsJS.getPath(Object) = gameDirectory.resolve(str) + KubeJS.verifyFilePath。
- 路径限制：verifyFilePath 只校验 toAbsolutePath().normalize().startsWith(gameDirectory)，否则抛 "You can't access files outside Minecraft directory!" → <server>/runtime_dump/ 允许。
- 父子目录：write 直接 Files.newBufferedWriter(path)，**没有 createDirectories** → 目录必须先存在。
- 写语义：newBufferedWriter 是 **truncate** 写；传 null/JsonNull 时 Files.deleteIfExists。**非原子写**。
- 输出格式：JsonWriter.setIndent("\t") → **tab 缩进 pretty JSON**（体积约为紧凑 jsonl 的 3–4 倍）。
- **设计变更**：不再写 _done.json/_loaded.json；完成与统计通过命令反馈回传（见第 1 节）。

## 4. 版本兼容

- 1.19.2 的 forge server jar 中 net/minecraft/core/registries/BuiltInRegistries.class **不存在**（unzip -l | grep -c = 0）；net/minecraft/core/Registry 存在并带各注册表字段。
- Rhino 的 mods/rhino-forge-1902.2.3-build.284.jar 内含 mm.jsmappings（717 KB，头部版本 1.19.2），提供 Mojmap→SRG 成员重映射；Registry.ITEM、entrySet、ItemStack.save、Component.translatable 的映射已由子代理用本地 Java 测试确认（f_122827_ -> ITEM 等，属本地验证、非服务器运行时）。
- **现有 assets/runtime_dump.js（v1）在 1.19.2 上会四类全 FAIL**：它只 Java.loadClass('...BuiltInRegistries')，且加载在各类函数内、外层 try/catch 只记日志 → 注册成功但产出 0 条。v2 的双版本 fallback 是必须的。

## 5. RCON 超时缺陷（评审 P0-1 的实测依据）

- aiomcrcon/client.py：async def send_cmd(self, cmd: str, timeout: float = 2.0)，内部 asyncio.wait_for(..., timeout) → **默认 2s 硬超时**；connect 同样 2s。
- Python 3.12：issubclass(TimeoutError, OSError) is True、asyncio.TimeoutError is TimeoutError → 当前 rcon_client.TRANSIENT_RCON_ERRORS 含 OSError，超时会走「重连 + 重发」循环 → **命令双执行**。
- 修法（design）：超时在 TRANSIENT 之前单独捕获 → 只重连不重发；timeout=None 必须真的不传参（传 None 给 wait_for = 永久等待）。

## 6. 规模与耗时证据

- 本服知识库现状（只读 items.db）：25,598 条 —— item 13,007 / block 11,019 / entity 695 / fluid 877；meta.dump.files=0（从未合并过运行时 dump）。
- 前例（1.20.1 副本，228 mods）：.trellis/tasks/archive/2026-10/10-21-modded-item-knowledge/research/02-runtime-dump.md —— 全量 dump **秒级**、产物约 4.5 MB、共 18,249 行（item 6,759 / block 4,247 / entity 931 / fluid 44 + recipe/recipetype）。
- **复制服全量实测（2026-10-24，同包同世界，0 人在线）**：`/researchdump` 端到端 0.30s，JS `duration_ms` 295ms（item 206 / block 69 / entity 6 / fluid 13）；条目 27,643（item 16,043 / block 9,729 / entity 826 / fluid 1,045），0 failed；文件合计约 6.2MB。watchdog 阈值 60s，余量极大。

## 7. 待实测清单（预演/线上补齐）

- [x] RCON 执行 /researchdump 的首次成功与失败形态（Unknown 文案）→ 见第 8 节
- [x] **命令反馈实测**：[rd] PROBE {...} 已被 RCON 原样带回（93B 文件、反馈单行）→ 见第 8 节
- [x] /reload 后命令真正可用的时间：脚本加载 → 可用约 5s → 见第 8 节（窗口 30s 足够，仍按预演调整）
- [x] 全量 25k 条的每类 duration_ms、四类文件体积（空服/副本）→ 见 8.2（295ms / 6.2MB）
- [x] 1.19.2 fallback（Registry）实际产出条数与 1.20.1 是否一致 → 见 8.2（四类 27,643 条全部成功）
- [x] 服务器无 watchdog 告警/崩服、在线玩家卡顿体感（全量 dump 时）→ 见 8.3（watchdog 0 次；只有首次 reload 3.5s 积压）
- [x] RCON 停机时的回执路径 → 编排层已实现「无法连接 → 手工四步」，用假 RCON 覆盖；未做真实停机破坏性演练


## 8. 预演实测（2026-10-24 19:51-19:55，线上服，1 人在线）

用临时分支 `prototype/runtime-dump-probe`（commit `74bc131`）里的 `prototype/runtime_dump_probe/`（一次性探针，已清理）实测；master 工作区不保留原型代码：

| 项 | 结果 |
|---|---|
| RCON 命令输出 | `list` 返回 `There are 1 of a max of 20 players online: Chaos_Fantasia` → 输出确实随响应回来 |
| 未注册命令文案 | `rdprobe` 返回 `Unknown or incomplete command, see below for error` |
| 部署 + reload | 19:52:16 `Scripts loaded`；19:52:21 第一次成功执行（Component 类才被加载）→ **脚本加载到命令可用约 5s** |
| JsonIO 写盘 | `runtime_dump/_probe.json` 93 bytes，tab 缩进 JSON；`numbers:[1,2,3]` 被写成 `[1.0,2.0,3.0]`（小整数浮点化） |
| 命令反馈 | RCON 收到 `[rd] PROBE {"ok":true,"version":"v1","ms":1.0}` → **sendSystemMessage 内容随 RCON 响应返回**（完成信号方案成立） |
| `/reload` 代价 | 命令自身 3.67s 返回 `Reloading!`；19:55:12 服务器日志出现 `Can't keep up! ... 3375ms or 67 ticks behind` → **1 人在线时约 3.4s tick 积压** |
| 清理 | 删脚本 + reload 后 `rdprobe` 恢复 `Unknown`，`runtime_dump/` 已删除，服务器无残留 |

**对设计的修正**：完成判定用命令反馈已实测成立；`/reload` 的代价要在「一键」路径里如实体现（只在脚本内容变化时 reload，并挑低峰/空服）。**全量 dump 的耗时与体积仍未测**（未在有玩家时执行）。


### 8.2 全量 dump 实测（复制服，0 人在线）

复制服：`/home/guigui/mc-probe/CTI-probe`（同包同世界，端口 21335 / RCON 25576），一次性脚本 `rd_dump_proto.js`（原型，见临时分支 `prototype/runtime-dump-probe`）。

| 项 | 结果 |
|---|---|
| fallback 分支 | `BuiltInRegistries` 不存在 → 自动退回 `net.minecraft.core.Registry`，四类均成功 |
| 耗时 | RCON 端到端 0.30s；JS `duration_ms` 295ms（item 206 / block 69 / entity 6 / fluid 13） |
| 条目 | 27,643（item 16,043 / block 9,729 / entity 826 / fluid 1,045），0 failed |
| 体积 | 约 6.2MB（item 4,010,309 B / block 1,863,108 / entity 150,268 / fluid 144,048） |
| schema 校验 | 27,643 个 id 全部能被 builder `_dump_id` 解析（bad_id=0，无重复）；item 的 `resolved`/`stack` 全非空；entity 11 条 `resolved` 为空；fluid 按设计无 tkey/resolved |
| 目录缺失 | 未预建 `runtime_dump/` 时四类全部 `NoSuchFileException` → 验证“插件必须先建目录” |
| 运行时 vs 静态 KB | 运行时唯一 id 18,619；静态 KB 25,598；交集 18,014；运行时新增 605（如 `aether_redux:thrown_spear`）；静态多出 7,584（含 loot-table id 等非注册表条目） |

**结论**：全量 dump 对 watchdog 无实质风险（0.3s）；首次部署的 `/reload` 才是唯一可见卡顿来源。

### 8.3 线上真机验收（2026-10-25 11:32-11:34，线上服，3 人在线）

实现完成后，用插件侧同一套代码（`RuntimeDumpRunner` + `kb.rebuild`，绕过 AstrBot 消息层直接调用）在线上服执行：

| 项 | 结果 |
|---|---|
| 首次一键流程 | 预建 `runtime_dump/` → 部署 `kubejs/server_scripts/runtime_dump.js` → `/reload`（RCON 返回 `Reloading!`，命令本身 ~3.5s）→ `/researchdump` **一次成功**（本机未出现 Unknown 窗口；注意 reload 的响应在 tick 积压后返回，此时命令表已就绪） |
| dump | 27,643 条（item 16,043 / block 9,729 / entity 826 / fluid 1,045），`failed: []`；首次 1.9s（类加载开销），第二次 322ms |
| 产物 | 与复制服逐字节一致：item 4,010,309 B / block 1,863,108 / entity 150,268 / fluid 144,048 |
| 自动重建 | 26,203 条（物品 13,058 / 方块 11,152 / 流体 1,196 / 实体 797），6.1s；回执 `运行时 dump：4 个文件，合并 27643 次（权威 has_item 覆盖 17,079 条）` |
| 二次触发 | 只发 `researchdump`、不 reload（记录到的命令序列 = `['researchdump']`）→ 懒部署生效 |
| reload 影响 | 11:32:56 出现一次 `Can't keep up! 3508ms or 70 ticks behind`；**无玩家断线**（日志无 leave）、watchdog 0 次、事后 TPS 20 / Overall tick 29.5ms |
| 截断容错 | 把真实 `item.json` 截半 → builder 跳过该文件并 warning（`Unterminated string ...`），同目录完好的 `block.json` 仍正常合并 9,729 条 |

**结论**：AC1/AC2 在线上成立；唯一可见影响是首次部署时的 ~3.5s tick 积压（与 8.2 预演一致）。`Unknown` 退避分支未在本次线上触发（属兜底），由编排层单测覆盖。

## 附：复现命令（只读）

```bash
# 类过滤器
unzip -p /home/guigui/mc/CTI0.46/mods/kubejs-forge-1902.6.2-build.73.jar \
  dev/latvian/mods/kubejs/BuiltinKubeJSPlugin.class | strings | grep -E 'java\.(io|nio)|deny'

# JsonIO 签名与不建父目录
d=$(mktemp -d); cd "$d"
unzip -o -q /home/guigui/mc/CTI0.46/mods/kubejs-forge-1902.6.2-build.73.jar \
  'dev/latvian/mods/kubejs/util/JsonIO.class'
javap -p -c dev/latvian/mods/kubejs/util/JsonIO.class | sed -n '/write(java.nio.file.Path/,/^$/p'

# 1.19.2 无 BuiltInRegistries
unzip -l /home/guigui/mc/CTI0.46/libraries/net/minecraftforge/forge/1.19.2-43.4.12/forge-1.19.2-43.4.12-server.jar | grep -c 'BuiltInRegistries'

# 就绪时序
unzip -o -q /home/guigui/mc/CTI0.46/mods/kubejs-forge-1902.6.2-build.73.jar \
  'dev/latvian/mods/kubejs/server/ServerScriptManager.class'
javap -p -c dev/latvian/mods/kubejs/server/ServerScriptManager.class | sed -n '/wrapResourceManager/,/^$/p'

# RCON 完成信号（阻塞 + 捕获反馈）
for j in /home/guigui/mc/CTI0.46/libraries/net/minecraftforge/forge/1.19.2-43.4.12/forge-1.19.2-43.4.12-server.jar \
         /home/guigui/mc/CTI0.46/libraries/net/minecraft/server/1.19.2-20220805.130853/server-1.19.2-20220805.130853-srg.jar; do
  unzip -o -q "$j" 'net/minecraft/server/dedicated/DedicatedServer.class' \
    'net/minecraft/server/rcon/RconConsoleSource.class' 'net/minecraft/util/thread/BlockableEventLoop.class' 2>/dev/null
done
javap -p -c net/minecraft/server/dedicated/DedicatedServer.class | sed -n '/m_7261_(java.lang.String)/,/^$/p'
javap -p -c net/minecraft/server/rcon/RconConsoleSource.class | sed -n '/m_213846_/,/^$/p'
javap -p -c net/minecraft/util/thread/BlockableEventLoop.class | sed -n '/m_18709_/,/^$/p'

# aiomcrcon 默认超时
sed -n '110,125p' /home/guigui/code/AstrBot/.venv/lib/python3.12/site-packages/aiomcrcon/client.py
```