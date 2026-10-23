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
| `enable_log_monitor` | 启用MC日志监控 | `false` |
| `log_server_host` | 日志服务器地址 | `127.0.0.1` |
| `log_server_port` | 日志服务器端口 | `25576` |
| `enable_chat_response` | 将LLM响应发送回MC聊天框 | `true` |
| `bot_nickname` | 在MC中显示的机器人昵称 | `"Bot"` |
| `enable_unified_context` | 启用MC和QQ群的统一上下文 | `false` |
| `unified_group_umo` | 统一上下文目标群UMO | `""` |
| `mc_message_prefix` | MC消息在统一上下文中的前缀 | `"[MC]"` |
| `mc_server_dir` | MC服务端根目录（含 mods/ 的路径）；留空则物品知识库不可用 | `""` |
| `mc_version` | MC版本（如 1.20.1）；留空自动从服务端目录探测 | `""` |
| `mc_client_dir` | 客户端 .minecraft 目录（可选）：离线取原版中文名、精确判断方块能否 give | `""` |
| `vanilla_zh_download` | 重建时自动下载官方原版 zh_cn.json（按版本、sha1校验、失败回退BMCLAPI） | `true` |
| `cfpa_auto_download` | 重建时自动下载 CFPA 汉化资源包（GitHub 失败回退 BMCLAPI） | `true` |

配置示例：
```json
{
  "rcon_host": "127.0.0.1",
  "rcon_port": 25575,
  "rcon_password": "your_password",
  "admin_ids": ["123456789", "Steve", "Alex"],
  "enable_dangerous_commands": false,
  "enable_log_monitor": true,
  "log_server_host": "127.0.0.1",
  "log_server_port": 25576,
  "enable_chat_response": true,
  "bot_nickname": "MC助手",
  "enable_unified_context": false,
  "unified_group_umo": "",
  "mc_message_prefix": "[MC]",
  "mc_server_dir": "/home/mc/server",
  "mc_version": "",
  "mc_client_dir": "",
  "vanilla_zh_download": true,
  "cfpa_auto_download": true
}
```

### 3. MC游戏内聊天支持（可选）

如果启用 `enable_log_monitor`，可以在MC游戏内直接与机器人对话：

1. **在MC服务器机器上运行日志服务器**：
   ```bash
   python log_server.py（注意，请自行修改代码文件配置参数）
   ```

2. **配置权限**：
   - `admin_ids` 中添加MC玩家名即可授予权限(你游戏名是啥就填啥)
   - 例如：`"admin_ids": ["Steve", "Alex"]` 允许这两个MC玩家执行管理命令
   - 格式：MC玩家的user_id为 `mc_player_{玩家名}`

3. **在MC中使用**：
   - 所有MC聊天消息都会提交到AstrBot，LLM会看到完整的聊天上下文
   - 唤醒词在AstrBot的 `wake_prefix` 配置中统一管理（如 `"wake_prefix": ["小面包"]`）
   - 只有包含唤醒词的消息才会触发LLM回复
   - 示例：发送 `小面包 查看在线玩家`，机器人会自动回复到MC聊天框

**权限校验说明**：
- QQ消息：使用QQ号校验（如 `"123456789"`）
- MC消息：使用玩家名校验（如 `"Steve"`）
- 系统会自动识别消息来源并应用对应的权限规则

### 4. 统一会话上下文（高级功能）

启用后，MC游戏内聊天和指定QQ群可以共享同一个对话上下文，实现跨平台无缝交流。

**功能特性**：
- 🔗 **统一上下文**：MC玩家和QQ群成员在同一对话中交流
- 🤖 **双向感知**：LLM能同时看到MC和QQ的消息历史
- 🎯 **定向推送**：支持将MC事件推送到指定QQ群
- 🛠️ **工具支持**：提供 `send_to_qq_group` 工具，让LLM主动向QQ群发送消息

**配置步骤**：

1. **获取QQ群UMO**：
   - 在目标QQ群中发送任意消息
   - 在AstrBot后台日志中查找类似 `aiocqhttp_default:GroupMessage:123456789` 的UMO字符串
   - 格式说明：`平台ID:消息类型:群号`

2. **启用统一上下文**：
   ```json
   {
     "enable_log_monitor": true,
     "enable_unified_context": true,
     "unified_group_umo": "aiocqhttp_default:GroupMessage:123456789",
     "mc_message_prefix": "[MC]"
   }
   ```

3. **工作原理**：
   - 所有MC聊天消息会自动提交到AstrBot的指定QQ群会话
   - MC消息会带有发送者昵称（如 `Steve(MC)`）
   - LLM能看到完整的MC和QQ混合对话历史
   - MC系统事件（登入、登出、成就、死亡）也会记录到会话上下文
   - LLM可使用 `send_to_qq_group` 工具主动向QQ群发送消息

**使用示例**：

```
[QQ群] 用户A: @Bot 服务器现在有多少人在线？
[MC] Steve: 有3个人，但是Alex好像挂机了
[QQ群] Bot: 当前在线3人：Steve、Alex、Notch。根据Steve的反馈，Alex可能在挂机。
[MC] Alex: 我没挂机！我在挖矿呢
[QQ群] Bot: 好的，Alex说他在挖矿，并没有挂机。
```

**注意事项**：
- 统一上下文需要先启用日志监控（`enable_log_monitor: true`）
- `unified_group_umo` 必须填写正确的UMO格式
- MC消息前缀可自定义，用于在QQ群中区分消息来源
- 所有MC消息都会提交到指定QQ群的会话上下文，由AstrBot的 `wake_prefix` 控制是否唤醒LLM

## 📖 使用方法

**无需命令前缀！** 直接与AstrBot对话即可管理服务器。

### 使用示例

```
用户: 查看在线玩家
Bot: 在线玩家: There are 3 of a max of 20 players online: Steve, Alex, Notch

用户: 把Steve踢出服务器，原因是挂机太久
Bot: 踢出玩家 Steve: Kicked Steve: 挂机太久

用户: 给Alex 64个钻石
Bot: 给予 Alex 64个 minecraft:diamond: Given [Diamond] x 64 to Alex

用户: 把时间调成白天
Bot: 设置时间为 day: Set the time to 1000

用户: 把天气变成晴天
Bot: 设置天气为 clear: Changed the weather to clear

用户: 封禁Hacker这个玩家
Bot: 封禁玩家 Hacker: Banned Hacker: 违反服务器规则

用户: 把难度调成困难
Bot: 设置难度为 hard: Set game difficulty to Hard

用户: 开启死亡不掉落
Bot: 设置游戏规则 keepInventory = true: Gamerule keepInventory is now set to: true
```

## 🛠️ 支持的功能

### 玩家管理
- ✅ 踢出玩家（kick）🔒
- ✅ 封禁/解封玩家（ban/pardon）🔒
- ✅ 管理OP权限（op/deop）🔒
- ✅ 白名单管理（whitelist add/remove）🔒

### 游戏操作
- ✅ 给予物品（give）🔒
- ✅ 传送玩家（tp）🔒
- ✅ 设置游戏模式（gamemode）🔒
- ✅ 杀死实体（kill）🔒
- ✅ 清空背包（clear）🔒
- ✅ 设置经验（xp）🔒

### 服务器管理
- ✅ 查看在线玩家（list）🆓
- ✅ 服务器广播（say）🔒
- ✅ 格式化消息（tellraw）🔒
- ✅ 屏幕标题（title）🔒
- ✅ 保存世界（save-all）🔒
- ✅ 查看白名单（whitelist list）🆓
- ✅ 查看封禁列表（banlist）🆓
- ✅ 执行自定义命令（execute_command）🔒
- ⚠️ 停止服务器（stop）🔒 - 需启用危险命令

### 世界操作
- ✅ 设置天气（weather）🔒
- ✅ 设置时间（time）🔒
- ✅ 设置难度（difficulty）🔒
- ✅ 设置游戏规则（gamerule）🔒
- ✅ 生成实体（summon）🔒

### 🆕 脚本执行器
- ✅ 执行Python脚本（execute_script）🔒
- ✅ 列出可用工具（list_script_tools）🆓

### 📚 物品知识库
- ✅ 搜索物品/方块/实体（search_mc_items）🆓
- ✅ 重建知识库（/mc_kb_rebuild）🔒
- ✅ 查看构建状态与覆盖率（/mc_kb_status）🔒

### 🔗 统一上下文工具
- ✅ 发送消息到QQ群（send_to_qq_group）🔒
  - 需要启用统一上下文功能
  - 允许LLM主动向配置的QQ群发送消息
  - 可用于向QQ群推送MC服务器事件或状态

**图标说明：**
- 🔒 需要管理员权限
- 🆓 无需权限，所有人可用

## 🎯 脚本执行器

插件内置了强大的脚本执行器，允许LLM编写Python脚本来完成复杂的自动化任务。


### 脚本功能特性

- ✅ **异步执行**：支持 async/await 语法
- ✅ **工具集成**：可调用所有40+个MC管理工具
- ✅ **超时控制**：默认60秒超时，可自定义
- ✅ **错误处理**：完善的异常捕获和错误报告
- ✅ **输出捕获**：自动捕获print输出



## 📚 物品知识库（可选）

LLM 知道 `minecraft:diamond_sword`，但不知道 278 个模组里哪个物品叫「黄铜锭」、ID 是 `create:brass_ingot`。
物品知识库离线扫描服务端 `mods/*.jar` 与整合包 `kubejs/`，还原 **完整ID ↔ 中英文名 ↔ 所属模组 ↔ 类型**，
并合并原版名称与 CFPA 汉化，让玩家说中文俗名也能查到可 `give` 的 ID。

### 使用步骤

1. 在插件配置里填写 `mc_server_dir`（MC 服务端根目录，含 `mods/` 的那个目录）。
2. 让管理员在聊天里执行 `/mc_kb_rebuild`（第一次会下载原版中文约 1.3 MB、CFPA 汉化包约 2 MB，之后走缓存）。
3. 之后直接对 LLM 说「给我 10 个黄铜锭」，它会先 `search_mc_items` 再 `give_item`；也可执行 `/mc_kb_status` 查看覆盖率。

### 数据目录

知识库是 **可重建的派生缓存**，删掉重跑 `/mc_kb_rebuild` 即可，不影响服务器：

```
AstrBot/data/plugin_data/mc_manager/
├── items.db                  # SQLite：物品/方块/流体/实体对照表
├── vanilla/zh_cn-1.20.1.json # 原版官方中文（运行时下载 / 服主手动放置）
├── cfpa/*.zip                # CFPA 汉化包缓存（也可手动放 zip 兜底）
├── zh_cn_extra.json          # 服主自定义中文名（可选）
└── runtime_dump/*.jsonl      # KubeJS 运行时权威导出（可选增强）
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

静态扫描看不到运行时动态注册的 ID。装了 KubeJS 的整合包可以：

1. 把 [assets/runtime_dump.js](assets/runtime_dump.js) 复制到 `<mc_server_dir>/kubejs/server_scripts/`，重启服务器或执行 `/reload`；
2. 进服执行 `/researchdump`——结果以 `##RD##` 前缀写进服务器日志 `logs/latest.log`（几万行，属正常）；
3. 执行 `python3 assets/extract_runtime_dump.py <mc_server_dir>/logs/latest.log`，
   生成 `<mc_server_dir>/runtime_dump/{item,block,entity,fluid}.jsonl`；
4. 再执行 `/mc_kb_rebuild`：运行时的注册表是权威数据，会覆盖静态扫描的名称与"能否 give"判断。

AstrBot 与 MC 不同机时，把 `runtime_dump/` 目录拷到插件数据目录 `data/plugin_data/mc_manager/runtime_dump/` 同样会被识别（同名文件取 mtime 新的）。

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
- `whitelist_list` - 查看白名单
- `banlist` - 查看封禁列表
- `list_script_tools` - 查看可用工具列表
- `search_mc_items` - 搜索物品知识库（物品/方块/实体的 ID 与中英文名）

### 🔴 需要权限（管理操作）
所有其他工具都需要管理员权限，包括：

- **玩家管理**：kick、ban、op等
- **游戏操作**：give、tp、gamemode等
- **服务器管理**：save、say、tellraw等
- **世界管理**：weather、time、difficulty等
- **脚本执行**：execute_script

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
6. **谨慎使用脚本执行器**：`execute_script` 可以调用任何已注册工具，请仅授予信任用户

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