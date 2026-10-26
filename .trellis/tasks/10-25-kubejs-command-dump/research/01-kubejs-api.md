# KubeJS 命令树导出 API 核实

## 结论

1. 两个目标版本都可使用 `ctx.source.getServer().getCommands().getDispatcher()` 获取当前活动 dispatcher。
2. `dispatcher.getAllUsage(dispatcher.getRoot(), ctx.source, false)` 一次即可 DFS 导出全树扁平路径，无需逐节点遍历。
3. 本任务选择 `restricted=false`：该分支不调用 `canUse(source)`，快照不随 OP2 玩家或 RCON4 触发身份变化，并保留玩家限定/高权限命令语法。
4. 两版本 Brigadier 的相关实现一致；KubeJS `CommandRegistryEventJS` 和 Rhino 重映射均支持该调用链。
5. 只能得到 `<name>` 形式的扁平 usage、可执行路径和 redirect 提示；不能得到参数可选性、类型、范围、建议值、权限等级或 mod 归属。

## 本地版本与实例

| 实例 | Minecraft / Forge | KubeJS | Rhino | Brigadier | 用途 |
|---|---|---|---|---|---|
| `/home/guigui/mc/CTI0.46` | 1.19.2 / 43.4.12 | 1902.6.2-build.73 | 1902.2.3-build.284 | 1.0.18 | 动态 `researchdump` 回归、vanilla 多分支 |
| `/home/guigui/mc/Farming` | 1.20.1 / 47.4.20 | 2001.6.5-build.16 | 2001.2.3-build.10 | 1.1.8 | `wine info`、`wine age <years>` 多分支与第二版本 |

两个实例均已获用户许可用于本任务的部署、reload 和启动实测；Farming 当前是不再使用的旧服务器。

## 调用链与生命周期

- `ServerEvents.commandRegistry(event => event.register(...executes(ctx => ...)))` 中，`ctx.source` 是 `CommandSourceStack`。
- `CommandSourceStack.getServer()` → `MinecraftServer.getCommands()` → `Commands.getDispatcher()` 的官方名在两个版本的 Rhino `mm.jsmappings` 中均有 SRG 映射。
- `/reload` 会替换 `MinecraftServer` 的 ReloadableResources → Commands → dispatcher 链。因此禁止缓存注册时的 `event.dispatcher`；必须在 `executes(ctx)` 内取活动链。
- 现有 `assets/runtime_dump.js` 已使用 `ctx.source.sendSystemMessage(...)` 和 `source.hasPermission(2)`，同类型 Rhino 访问已在 CTI 跑通。

最小导出核心：

```js
const dispatcher = ctx.source.getServer().getCommands().getDispatcher()
const usages = dispatcher.getAllUsage(dispatcher.getRoot(), ctx.source, false)
const entries = []
for (let i = 0; i < usages.length; i++) entries.push(String(usages[i]))
```

使用 `usages.length`、索引和 `String()`；不要依赖未验证的 `Java.from()`、ES6 展开或 `Array.from`。

## `getAllUsage` 精确行为

Brigadier 递归逻辑的关键点：

- `restricted && !node.canUse(source)` 时剪掉整棵子树；`restricted=false` 不读取 source。
- 节点有 command 时输出当前完整 prefix；command 与 children 可同时输出。
- argument 的 `getUsageText()` 恒为 `<name>`，不区分 required/optional。
- redirect 输出 `prefix -> targetUsageText`，目标为 root 时输出 `prefix ...`；redirect children 不在该位置继续展开。
- 仅作中间层且没有 command/redirect 的 literal 不产生自己的行，子路径仍保留。
- 输出不带前导 `/`，分隔符为空格。

1.19.2 的 Brigadier 1.0.18 与 1.20.1 的 1.1.8，本地 `javap -p -c` 对比显示 `getAllUsage` public/private 方法和 `ArgumentCommandNode.getUsageText()` 指令一致。

### 为什么不用 `restricted=true`

`true` 会让结果取决于触发者权限和非玩家 source 条件，且可能剪掉执行体要求玩家的模组命令。`CommandSourceStack.withPermission(4)` 虽存在，也只能得到等级 4 视角，不符合本期“完整可执行语法、level 可为 null”的目标。

## 现有写入与消费侧事实

- `assets/runtime_dump.js` 的 `JsonIO.write('runtime_dump/<kind>.json', {kind,count,entries})` 已验证；`runtime_dump.py` 负责预建目录。
- 当前 `rdDump()` 没有 ctx 参数，需要改为在执行体内接收活动 source；`counts` 当前只有 item/block/entity/fluid。
- `kb/commands.py` 当前只读数据目录 `runtime_dump/commands.jsonl`；canonical `commands.json` 的发布和查询接线属于本子任务。
- `kb/builder.py` 会把 runtime_dump 下任意可读 JSON 计入 `info["files"]`。命令条目没有合法物品 id，不会进入物品库，但会改变 `kubejs_hint`；因此必须显式排除 commands 文件。

## 实测重点

- CTI：部署更新脚本、reload、触发 dump；断言包含 `researchdump` 和 vanilla `execute` 多分支，四类物品/方块/实体/流体仍成功。
- Farming：启动后部署并触发；断言包含 `wine info`、`wine age <years>`，验证 2001 KubeJS 调用链。
- 两实例记录 count、文件大小、耗时和 failed；命令类别失败不得产生或发布部分快照。
- 离线夹具覆盖 literal、argument、多分支、redirect、去重、坏 JSON/schema 和旧缓存保留。

## 限制与已排除路径

- 不缓存 event.dispatcher，不承诺参数可选性或类型，不把 redirect 行当命令串。
- 快照依赖当前服务器 mods/datapacks，跨服不可复现。
- Mojang/brigadier GitHub 没有 1.1.8/1.1.9 tag；第二版本以本地 jar 字节码为证据。
- KubeJS 在线仓库抓取不稳定；以本地 jar、`javap`、Rhino 映射和官方 wiki 交叉核实。

## Sources

- [Mojang Brigadier 1.0.18 — CommandDispatcher.java](https://raw.githubusercontent.com/Mojang/brigadier/1.0.18/src/main/java/com/mojang/brigadier/CommandDispatcher.java)
- [Mojang Brigadier 1.0.18 — ArgumentCommandNode.java](https://raw.githubusercontent.com/Mojang/brigadier/1.0.18/src/main/java/com/mojang/brigadier/tree/ArgumentCommandNode.java)
- [Mojang Brigadier 1.0.18 — CommandNode.java](https://raw.githubusercontent.com/Mojang/brigadier/1.0.18/src/main/java/com/mojang/brigadier/CommandNode.java)
- [KubeJS wiki — Commands](https://kubejs.com/wiki/tutorials/chat)
- [KubeJS legacy wiki — Command Registry](https://wiki.latvian.dev/books/kubejs-legacy/page/command-registry)
- 本地可复现中间物：`/tmp/rdres/`；仓库证据：`assets/runtime_dump.js`、`runtime_dump.py`、`kb/commands.py`、`kb/builder.py`。
