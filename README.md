# AstrBot MC服务器管理插件

通过LLM智能管理Minecraft服务器的AstrBot插件。支持Fabric、Forge、NeoForge等所有使用标准RCON协议的服务器。

## ✨ 功能特性

- 🤖 **自然语言交互**：无需命令前缀，直接与LLM对话即可管理服务器
- 🎮 **全面管理**：支持玩家管理、游戏操作、服务器管理、世界操作等功能
- 🔒 **权限控制**：支持管理员白名单，确保服务器安全
- 🌐 **跨平台兼容**：基于RCON协议，支持Fabric、Forge、NeoForge等各种服务端
- 📚 **物品知识库（可选）**：扫描服务端 mods/ 与整合包 kubejs/，把模组物品的完整ID、中英文名、所属模组建成可搜索的库；LLM 说「黄铜锭」也能查到 `create:brass_ingot` 并直接 give

## 📦 安装

### 方法一：通过AstrBot插件市场安装（推荐）

1. 打开AstrBot管理面板
2. 进入「插件管理」
3. 搜索 `mc_manager`
4. 点击安装

### 方法二：手动安装

1. 下载本插件到 AstrBot 的 `data/plugins/` 目录
2. 重启 AstrBot

## ⚙️ 配置

### 1. Minecraft服务器配置

在您的MC服务器 `server.properties` 文件中启用RCON：

```properties
enable-rcon=true
rcon.port=25575
rcon.password=your_secure_password
broadcast-rcon-to-ops=true
```

**重要**：修改后需要重启MC服务器。

### 2. 插件配置

在AstrBot管理面板中配置本插件：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `rcon_host` | MC服务器地址 | `localhost` |
| `rcon_port` | RCON端口 | `25575` |
| `rcon_password` | RCON密码 | - |
| `admin_ids` | 管理员ID列表（QQ号或MC玩家名） | `[]`（空表示所有人可用） |
| `enable_dangerous_commands` | 启用危险命令（如stop） | `false` |
| `enable_chat_response` | 将LLM响应发送回MC聊天框 | `true` |
| `bot_nickname` | 在MC中显示的机器人昵称 | `"Bot"` |
| `enable_unified_context` | 启用MC和QQ群的统一上下文 | `false` |
| `enable_system_event_context` | 系统事件（进退服/死亡/成就）也注入LLM上下文 | `false` |
| `system_event_push` | 系统事件推送到绑定群，分组内按 `join`/`leave`/`death`/`advancement` 独立开关（老的 `enable_system_event_forward` 已移除） | 组内四项全 `false` |
| `unified_group_umo` | 绑定群UMO（推荐用 `mc绑定` 命令自动设置，无需手填） | `""` |
| `mc_bridge_prefix` | 游戏内聊天转发到QQ群的前缀（留空=全转） | `"mc喊话"` |
| `mc_message_prefix` | 转发到QQ群的MC消息前缀 | `"[MC]"` |
| `mc_server_dir` | MC服务端根目录（含 mods/ 的路径）；物品知识库与MC聊天监听都需要它 | `""` |
| `mc_version` | MC版本（如 1.20.1）；留空自动从服务端目录探测 | `""` |
| `mc_client_dir` | 客户端 .minecraft 目录（可选）：离线取原版中文名、精确判断方块能否 give | `""` |
| `vanilla_zh_download` | 重建时自动下载官方原版 zh_cn.json（按版本、sha1校验、失败回退BMCLAPI） | `true` |
| `cfpa_auto_download` | 重建时自动下载 CFPA 汉化资源包（GitHub 失败回退 BMCLAPI） | `true` |

> **升级提示**：旧版的 `enable_system_event_forward` 已移除，升级后进服/退服/死亡/成就四类系统事件推送**默认全部关闭**，需要在面板的"系统事件推送到群"分组里重新勾选要推送的类型。

配置示例：
```json
{
  "rcon_host": "127.0.0.1",
  "rcon_port": 25575,
  "rcon_password": "your_password",
  "admin_ids": ["123456789", "Steve", "Alex"],
  "enable_dangerous_commands": false,
  "enable_chat_response": true,
  "bot_nickname": "MC助手",
  "enable_unified_context": false,
  "enable_system_event_context": false,
  "system_event_push": {
    "join": false,
    "leave": false,
    "death": false,
    "advancement": false
  },
  "unified_group_umo": "",
  "mc_bridge_prefix": "mc喊话",
  "mc_message_prefix": "[MC]",
  "mc_server_dir": "/home/mc/server",
  "mc_version": "",
  "mc_client_dir": "",
  "vanilla_zh_download": true,
  "cfpa_auto_download": true
}
```

### 3. MC游戏内聊天支持（自动）

只要配置了 `mc_server_dir`（MC 服务端根目录），插件会**自动监听** `logs/latest.log`：
- 无需在 MC 服务器上运行任何额外脚本（旧的 log_server.py 方式已废弃删除）
- MC 服务器启动后自动开始监听，停止/重启后自动恢复，无需重载插件
- 要求 AstrBot 与 MC 服务端在**同一台机器**

**在游戏里与机器人对话**：
- 所有MC聊天消息都会提交到AstrBot，LLM会看到完整的聊天上下文
- 唤醒词在AstrBot的 `wake_prefix` 配置中统一管理（如 `"wake_prefix": ["小面包"]`）
- 只有包含唤醒词的消息才会触发LLM回复
- 示例：发送 `小面包 查看在线玩家`，机器人会自动回复到MC聊天框

**权限校验说明**：
- `admin_ids` 中添加MC玩家名即可授予权限（你游戏名是啥就填啥）
- QQ消息使用QQ号校验，MC消息使用玩家名校验，系统自动识别来源
- MC玩家的user_id格式为 `mc_player_{玩家名}`

### 4. 群绑定与聊天互通

在目标QQ群里发一条命令即可绑定，无需手抄任何配置：

| 命令 | 说明 | 权限 |
|------|------|------|
| `mc绑定` | 把当前群绑定为MC消息转发目标 | 管理员 |
| `mc解绑` | 解除绑定，停止转发 | 管理员 |
| `mc喊话 <内容>` | 把消息发送到MC游戏内聊天（带QQ昵称前缀） | 绑定群成员，5秒冷却 |

绑定后自动生效的功能：
- 📨 **MC→QQ 传话**：游戏内发送以 `mc喊话` 开头的消息会转发到绑定群（前缀可用 `mc_bridge_prefix` 配置修改或留空全转）；系统事件（进服/退服/死亡/成就，带 `[MC]` 前缀）按 `system_event_push` 分组里的独立开关分别推送，默认全关
- 💬 **QQ→MC 喊话**：`mc喊话` 命令经 RCON 把消息送进游戏
- 🤖 **LLM 传话**：MC玩家通过唤醒词与LLM对话，回复自动回到游戏；LLM 也可用 `send_to_qq_group` 工具主动向绑定群发消息

**平台兼容性**：绑定命令自动捕获当前群会话（UMO），OneBot（aiocqhttp）与QQ官方机器人（qq_official）等平台均可使用。
> QQ官方机器人注意：其主动推送要求目标群在机器人启动后至少有过一条消息，且有腾讯官方配额限制；机器人重启后在群里任意发言一次即可恢复推送。

**统一上下文（可选）**：开启 `enable_unified_context` 后，MC聊天会注入绑定群的LLM会话上下文——LLM 能同时看到MC和QQ的消息历史，实现跨平台无缝交流。系统事件注入由 `enable_system_event_context` 单独控制。

**使用示例**：

```
[QQ群] 用户A: @Bot 服务器现在有多少人在线？
[MC游戏内] Steve: 小面包 有几个人在线？
[QQ群] Bot: 当前在线3人：Steve、Alex、Notch。
[MC游戏内] Alex: mc喊话 我没挂机！我在挖矿呢
[QQ群] [MC] <Alex> 我没挂机！我在挖矿呢
[QQ群] 用户A: mc喊话 Alex加油挖矿
[MC游戏内] [群聊] 用户A: Alex加油挖矿
```

## 📖 使用方法

**无需命令前缀！** 直接与AstrBot对话即可管理服务器。

### 使用示例

```
用户: 查看在线玩家
Bot: 在线玩家: There are 3 of a max of 20 players online: Steve, Alex, Notch

用户: 把Steve踢出服务器，原因是挂机太久
Bot: 执行命令 'kick Steve 挂机太久': Kicked Steve: 挂机太久

用户: 给Alex 64个钻石
Bot: 给予 Alex 64个 minecraft:diamond: Given [Diamond] x 64 to Alex

用户: 把时间调成白天
Bot: 设置时间为 day: Set the time to 1000

用户: 把天气变成晴天
Bot: 设置天气为 clear: Changed the weather to clear

用户: 封禁Hacker这个玩家
Bot: 执行命令 'ban Hacker 违反服务器规则': Banned Hacker: 违反服务器规则

用户: 把难度调成困难
Bot: 执行命令 'difficulty hard': Set game difficulty to Hard

用户: 开启死亡不掉落
Bot: 执行命令 'gamerule keepInventory true': Gamerule keepInventory is now set to: true
```

## 🛠️ 支持的功能

插件只保留少量高价值专用工具，其余 MC 命令统一由 `execute_command` 通用工具执行，
LLM 不确定命令写法时会先查 `search_mc_commands` 内置命令知识库。

### 🟢 信息查询（🆓 无需权限）
- ✅ 查看在线玩家（list_players）
- ✅ 搜索物品/方块/实体知识库（search_mc_items）
- ✅ 搜索MC命令用法（search_mc_commands）：内置原版清单 + 服务器导出的模组命令树；原版命令可直接用中文描述搜，
  模组命令用英文根名/参数概念词搜（中文意图先提炼成英文词，多个词空格隔开、顺序不限）

### 🎮 高频游戏操作（🔒）
- ✅ 给予物品（give_item）：支持模组物品完整ID；配置 `enable_public_give_item` 可放开给普通玩家（免权限）
- ✅ 传送玩家（teleport_player）
- ✅ 设置游戏模式（set_gamemode）：支持中文「生存/创造/冒险/旁观」
- ✅ 设置天气（set_weather）/ 设置时间（set_time）：支持中文
- ✅ 生成实体（summon_entity）：支持模组实体完整ID

### 💬 消息与互通（🔒）
- ✅ 公屏格式化消息（tellraw）：MC 聊天桥的回复出口
- ✅ 发送消息到QQ群（send_to_qq_group）
  - 需要先绑定群（管理员在群里发 mc绑定）
  - 允许LLM主动向绑定的QQ群发送消息

### 🔧 通用命令执行（🔒）
- ✅ 执行任意命令（execute_command）：踢人、封禁、白名单、难度、游戏规则、屏幕标题、
  保存世界等一切没有专用工具的操作都走它；不确定用法时先查 search_mc_commands
- ⚠️ `stop`、`ban-ip` 为危险命令，默认拦截，需在配置中启用 `enable_dangerous_commands`

### 📚 物品知识库
- ✅ 搜索物品/方块/实体（search_mc_items）🆓
- ✅ 重建知识库（/mc_kb_rebuild）🔒
- ✅ 一键导出运行时数据并重建（/mc_kb_dump）🔒
- ✅ 查看构建状态与覆盖率（/mc_kb_status）🔒

**图标说明：**
- 🔒 需要管理员权限
- 🆓 无需权限，所有人可用

## 📚 物品知识库（可选）

LLM 知道 `minecraft:diamond_sword`，但不知道 278 个模组里哪个物品叫「黄铜锭」、ID 是 `create:brass_ingot`。
物品知识库离线扫描服务端 `mods/*.jar` 与整合包 `kubejs/`，还原 **完整ID ↔ 中英文名 ↔ 所属模组 ↔ 类型**，
并合并原版名称与 CFPA 汉化，让玩家说中文俗名也能查到可 `give` 的 ID。

### 使用步骤

1. 在插件配置里填写 `mc_server_dir`（MC 服务端根目录，含 `mods/` 的那个目录）。
2. 让管理员在聊天里执行 `/mc_kb_rebuild`（第一次会下载原版中文约 1.3 MB、CFPA 汉化包约 2 MB，之后走缓存）。
   装了 KubeJS 的整合包可以先执行 `/mc_kb_dump`，一条指令完成运行时注册表导出 + 重建（见下节）。
3. 之后直接对 LLM 说「给我 10 个黄铜锭」，它会先 `search_mc_items` 再 `give_item`；也可执行 `/mc_kb_status` 查看覆盖率。

### 数据目录

知识库是 **可重建的派生缓存**，删掉重跑 `/mc_kb_rebuild` 即可，不影响服务器：

```
AstrBot/data/plugin_data/astrbot_plugin_mc_manager/
├── items.db                  # SQLite：物品/方块/流体/实体对照表
├── vanilla/zh_cn-1.20.1.json # 原版官方中文（运行时下载 / 服主手动放置）
├── cfpa/*.zip                # CFPA 汉化包缓存（也可手动放 zip 兜底）
├── zh_cn_extra.json          # 服主自定义中文名（可选）
└── runtime_dump/
    ├── *.json                # 物品/方块/实体/流体（KubeJS 运行时权威导出）
    └── commands.json         # 命令树快照（search_mc_commands 消费，可只复制本文件跨机使用）
```

### 自定义中文名（zh_cn_extra.json）

顶层 JSON 对象，key 支持完整 ID 或语言键形态，value 是中文名（优先级最高，会覆盖自动合并结果）：

```json
{
  "create:brass_ingot": "黄铜锭",
  "item.create.cogwheel": "齿轮"
}
```

### 运行时 dump（可选增强，解决「服务端私货/动态注册」物品）

静态扫描看不到运行时动态注册的 ID。装了 KubeJS 的整合包用一条指令即可：

- 管理员执行 `/mc_kb_dump`：插件自动把 [assets/runtime_dump.js](assets/runtime_dump.js) 部署到
  `<mc_server_dir>/kubejs/server_scripts/`（内容没变就不重复写）、按需 `/reload`、
  通过 RCON 执行 `/researchdump` 并等它结束，最后自动重建知识库并回执各类别条数。
- 结果写到 `<mc_server_dir>/runtime_dump/{item,block,entity,fluid}.json` 与 `commands.json`（命令树）；
  运行时注册表是权威数据，会覆盖静态扫描的名称与"能否 give"判断。
- 首次执行会 `/reload`（约 3~4 秒 tick 积压，建议避开高峰），之后脚本内容不变就不再 reload。
- 前提：KubeJS 的 `gameDirectory` 必须等于 `mc_server_dir`（启动脚本先 `cd` 到服务器目录再 `java`），
  否则 JsonIO 会把文件写到别处、插件读不到。

自动流程不可用时的手工四步：

1. `mkdir -p <mc_server_dir>/runtime_dump`（KubeJS 的写盘 API 不会自动建目录）；
2. 把 `assets/runtime_dump.js` 复制到 `<mc_server_dir>/kubejs/server_scripts/`，重启服务器或执行 `/reload`；
3. 游戏内 OP（权限等级 ≥2）或控制台执行 `/researchdump`，生成 `runtime_dump/{item,block,entity,fluid,commands}.json`；
4. 执行 `/mc_kb_rebuild` 重建（会同时导入 `commands.json` 命令快照）。

AstrBot 与 MC 不同机时，把 `runtime_dump/` 目录拷到插件数据目录
`data/plugin_data/astrbot_plugin_mc_manager/runtime_dump/` 同样会被识别（`.json` 优先；旧版 `.jsonl` 仍兼容，可删）。
只复制 `commands.json` 即可迁移命令查询，但不等于迁移完整物品知识库（物品仍需要 `mc_server_dir` 与 `mods/`）。

### 命令知识库（运行时命令树）

同一份 dump 会把服务端当前命令树导出为 `runtime_dump/commands.json`（`kind=commands`，
`producer=kubejs`），并由 `/mc_kb_dump` 或 `/mc_kb_rebuild` 发布到插件数据目录。
之后 `search_mc_commands` 能按根命令名或参数语法查到模组命令（如 `wine info` / `wine age <years>`），
没有快照时仍按内置原版清单回答。模组命令只有英文命令名与参数语法、没有中文说明，中文意图需要调用方
先提炼成英文概念词（「陈酿」→ `wine`、「传送石碑」→ `waystone`）；多词查询按空格拆成无序 token
全部命中同一根才返回（`quest editing` 与 `editing quest` 等价），`channel mode` / `channel_mode` /
`channel-mode` 都命中 `channelmode`，同根内覆盖全部 token 的 usage 优先展示。边界：

- 首次部署 `runtime_dump.js` 会触发一次 `/reload`；实测部分模组命令（如 AE2 的 `/ae2 …`）在 reload 后会从命令树消失，
  此时导出的快照会缺这些根。需要完整命令树时，重启服务器后再执行一次 `/mc_kb_dump`（脚本已部署，不会再 reload）。

- 语法来自当前 dispatcher 已注册的完整 usage 路径（`getAllUsage(..., restricted=false)`），
  **不代表当前 RCON/玩家必然可执行**：实际执行仍受权限等级、命令来源和执行体内部检查限制。
- `redirect`（别名指向）只作为提示展示，不作为可直接拼装的完整命令。
- 参数只有 `<name>` 形式，不提供可选性/类型/范围；模组归属与权限等级无法可靠取得，
  运行时条目的来源显示「未知」、权限显示未知。**有全量快照时原版根也被运行时条目覆盖**，
  所以权限同样显示未知；只有在没有快照、或快照里缺该根时，内置原版条目才显示原版权限。
- 快照是原子发布的派生缓存：坏文件、截断或 count 不符会被拒绝，旧有效快照保持可查；
  单根命令最多展示 8 条 usage，超出会提示细化关键词。
- 无 KubeJS 的服务器计划用 RCON `help` 回退采集（任务 `10-25-rcon-help-command-fallback`，
  **尚未实现**；届时快照 `producer=rcon`，深层分支是压缩语法，查询会标注降级说明）。

### 限制与说明

- **AstrBot 与 MC 服务器不同机时无法离线扫描 jar**（RCON 不提供文件访问）。此时可把 CFPA zip 手动放进数据目录的 `cfpa/`；知识库本身仍需要同机或挂载同一目录。
- 内置"不同机"替代路径之外的方案不在本插件范围内；`mc_server_dir` 必须能被 AstrBot 进程读到。
- 原版名称来自本机安装的官方语言文件（Forge 的 `server-*-extra.jar`）或运行时下载，**插件不分发任何 Minecraft 资源**（遵守 Mojang EULA / Usage Guidelines）。
- 1.20.1 有 33 个原版条目（17 个锻造模板 + 16 个墙旗）官方语言文件里本来就没有名字，库里只能显示 ID，属已知例外。
- 原版方块「能否 give」在没有客户端目录时用掉落表近似（约 91% 精确 / 99% 召回），查询结果会标注「推测可 give」；配置 `mc_client_dir` 后按客户端模型精确判定。
- CFPA 汉化包翻译数据来自 [CFPA Minecraft-Mod-Language-Package](https://github.com/CFPAOrg/Minecraft-Mod-Language-Package)，许可 **CC BY-NC-SA 4.0**；插件运行时下载，不随插件分发。

## 🔐 权限分级说明

插件的所有工具按照危险程度分为不同等级：

### 🟢 无需权限（只读操作）
以下工具仅查询信息，不会修改服务器状态，**任何用户**都可以使用：

- `list_players` - 查看在线玩家
- `search_mc_items` - 搜索物品知识库（物品/方块/实体的 ID 与中英文名）
- `search_mc_commands` - 搜索 MC 命令用法（内置原版清单 + 可选的运行时命令树快照）

### 🔴 需要权限（管理操作）
所有其他工具都需要管理员权限，包括：

- **游戏操作**：give_item、teleport_player、set_gamemode、summon_entity 等
  - 例外：配置 `enable_public_give_item: true` 后 give_item 免权限（默认关，生存服慎用）
- **世界操作**：set_weather、set_time 等
- **消息互通**：tellraw、send_to_qq_group
- **通用执行**：execute_command（踢人/封禁/白名单/难度/游戏规则等一切其他命令）
  - whitelist/banlist 属于管理功能（游戏内需 3 级权限），查看也走 execute_command

### 权限配置示例

```json
{
  "admin_ids": ["123456789", "Steve", "Alex"]
}
```

- 留空 `[]`：所有人都有权限（**仅用于测试**）
- 添加QQ号：QQ用户权限控制
- 添加玩家名：MC玩家权限控制

##  安全建议

1. **设置强密码**：RCON密码应该使用强密码
2. **限制管理员**：在 `admin_ids` 中明确指定可以使用的用户
3. **生产环境必须配置管理员列表**：不要留空 `admin_ids`
4. **禁用危险命令**：保持 `enable_dangerous_commands` 为 `false`，除非确实需要
5. **防火墙配置**：如果MC服务器和AstrBot不在同一台机器，确保RCON端口的安全

## 🔧 故障排除

### 连接失败

**如何开启RCON：**

1. **找到服务器配置文件**：在MC服务器根目录找到 `server.properties` 文件
2. **编辑配置文件**：使用文本编辑器打开，添加或修改以下配置：
   ```properties
   enable-rcon=true
   rcon.port=25575
   rcon.password=your_secure_password
   broadcast-rcon-to-ops=true
   ```
3. **设置安全密码**：将 `your_secure_password` 替换为强密码
4. **重启服务器**：保存文件后，**必须重启MC服务器**才能生效
5. **验证配置**：服务器启动后，查看日志确认 "RCON running on..." 字样

**故障排查步骤：**

1. 确认MC服务器已启动
2. 确认 `server.properties` 中已启用RCON（`enable-rcon=true`）
3. 确认端口号和密码正确
4. 确认防火墙允许RCON端口
5. 如果MC和AstrBot在不同机器，确认 `rcon_host` 设置为MC服务器的IP地址而非 `localhost`

### 命令无响应

1. 检查AstrBot是否正确配置了LLM提供者
2. 检查插件配置是否正确
3. 查看AstrBot日志获取详细错误信息

## 📝 更新日志

### v1.5.0
- ✨ 新增 `/mc_kb_dump`：一条指令完成运行时 dump 与知识库重建
  - 自动部署 assets/runtime_dump.js（内容比对，未变不重复写）、按需 `/reload`
  - 用命令反馈判断完成（RCON 会阻塞到命令执行结束），不再依赖日志 `##RD##` 与提取脚本
  - 产物改为 `runtime_dump/{item,block,entity,fluid}.json`（KubeJS JsonIO 直写）
  - dump 期间其它 RCON 命令串行排队；长命令超时只重连、不重发，避免重复执行
- 🔥 移除 assets/extract_runtime_dump.py（日志提取层退役；旧 `.jsonl` 产物仍可读取）
- 📚 runtime_dump.js 同时兼容 1.19.2（Registry fallback）与 1.20.1+（BuiltInRegistries）

### v1.4.0
- ♻️ LLM 工具大幅精简（30 → 12）
  - 删除 17 个低频命令薄封装（kick/ban/op/whitelist/kill/clear/xp/say/title/save_world/difficulty/gamerule 等），统一由 `execute_command` 通用工具执行
  - whitelist/banlist 查询收回管理员（游戏内本就是 3 级权限命令）
  - 免权限只读工具收敛为：list_players、search_mc_items、search_mc_commands
- ✨ 新增 `search_mc_commands` 免权限工具
  - 内置原版 MC 命令固定知识库（assets/vanilla_commands.json），支持命令名/中文描述模糊搜索
  - LLM 调 execute_command 前可先查命令语法与权限等级；为模组命令导出（runtime dump）预留合并入口
- 🔥 移除脚本执行器（execute_script / list_script_tools / script_executor.py）
  - 安全原因：插件内 exec 执行 LLM 生成代码且默认配置下权限检查失效，等同进程级 RCE
  - 多步批量操作改用 AstrBot 自带的电脑使用能力（computer_use_runtime）+ 多轮工具调用

### v1.3.0
- ✨ 新增物品知识库（可选）
  - 离线扫描服务端 mods/ 与整合包 kubejs/，还原模组物品 ID + 中英文名
  - 新增 `search_mc_items` 只读工具（无需权限），支持中文名/英文名/完整ID 模糊搜索
  - 新增 `/mc_kb_rebuild`、`/mc_kb_status` 指令
  - 原版 ID/英文名取自服务端安装，中文按版本运行时下载；合并 CFPA 汉化包（CC BY-NC-SA 4.0）
  - 支持 `zh_cn_extra.json` 自定义译名与 KubeJS 运行时 dump 增强
  - 附运行时导出脚本 assets/runtime_dump.js 与日志转换脚本 assets/extract_runtime_dump.py
- 🐛 修复模组物品/方块/实体无法操作的问题
  - give / clear / summon / fill 不再强制给 ID 加 `minecraft:` 前缀，`create:brass_ingot` 这类完整 ID 可直接使用（原版短名行为不变）

### v1.2.0
- ✨ 新增统一会话上下文功能
  - 支持MC游戏内聊天和QQ群共享对话上下文
  - LLM可同时感知MC和QQ的消息历史
  - 新增 `send_to_qq_group` 工具，LLM可主动向QQ群发送消息
  - MC系统事件（登入、登出、成就、死亡）自动记录到上下文
- 🔧 优化消息处理
  - 改进MC消息提交机制，支持与AstrBot唤醒词无缝集成
  - 过滤Agent多轮调用的中间响应，避免发送无效内容到MC
- 📚 文档完善
  - 添加统一会话上下文配置和使用说明
  - 完善UMO获取和配置步骤

### v1.1.0
- ✨ 新增脚本执行器功能
  - 允许LLM编写Python脚本执行复杂任务
  - 支持异步执行和超时控制
  - 完善的错误处理和输出捕获
- 🔓 权限优化
  - 4个只读工具无需权限：list_players、whitelist_list、banlist、list_script_tools
  - 所有管理操作工具保留权限控制
- 📚 文档完善
  - 添加脚本执行器详细文档
  - 添加权限分级说明

### v1.0.0
- 初始版本
- 支持玩家管理、游戏操作、服务器管理、世界操作
- 支持LLM智能理解自然语言（无需命令前缀）
- 支持管理员权限控制

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交Issue和Pull Request！

## 💬 支持

如有问题，请在GitHub仓库提交Issue。