# 技术设计：聊天互通重构（本地日志直连）

## 架构总览

```
MC 服务端 (同机)                AstrBot 进程 (本插件)
┌──────────────────┐           ┌────────────────────────────────┐
│ logs/latest.log  │◄──轮询────│ LogWatcher (新, log_watcher.py)│
└──────────────────┘           │  - 1s 轮询 + 轮转检测           │
                               │  - 正则解析 → 事件回调          │
                               └───────┬────────────────────────┘
                                       │ 事件 (chat/join/leave/...)
                               ┌───────▼────────────────────────┐
                               │ main.py                        │
                               │  - 转发绑定群 (send_message)   │──► QQ 群 (任意平台)
                               │  - 统一上下文 (伪造事件注入)   │
                               │  - 唤醒→LLM→回复               │
                               └───────┬────────────────────────┘
                                       │ RCON tellraw (字节预算切段)
                               ┌───────▼────────────────────────┐
                               │ MC 游戏内聊天                   │
                               └────────────────────────────────┘
```

QQ→MC 仅两个入口：LLM 回复（现状保留）+ `mc喊话` 命令（新增）。MC→QQ：聊天+系统事件推送到绑定群。

## 模块边界

### 1. log_watcher.py（新增，替换 log_client.py + log_server.py）
- 职责：轮询 `{mc_server_dir}/logs/latest.log`，检测轮转，解析事件，回调上层。**不 import AstrBot 平台相关 API**（logger 除外），保持可独立测试。
- 轮询：1s 间隔；启动时从文件尾起步（不回放历史）；文件缺失时静默等待（missing_polls 计数，不打 error）。
- 轮转检测（务实裁剪为三判据）：① 文件变短；② inode 变化；③ 文件头 256B 指纹变化。判轮转后从头读。Linux 同机部署下足够，不抄 Scintilla 全部四判据+md5 兜底。
- 半行缓冲：readline 读到的非换行结尾残留计入下次拼接，避免截断行误判。
- 编码嗅探：首次读取时 UTF-8 / GBK 评分择优，之后固定（服务端日志编码不会中途变）。
- IO 隔离：文件 IO 放 daemon 单线程执行器，单次 15s 超时，单飞——防止 NFS/磁盘卡死拖住事件循环（借鉴 Scintilla，不照搬其完整实现）。
- 热重载防护：任务代际计数，stop() 后旧代际任务直接退出；所有 task 持引用登记，terminate 时统一 cancel。
- 解析正则：从 log_client.py 原样搬迁 CHAT/JOIN/LEAVE/ADVANCEMENT/DEATH 五类（行为不退步；已知局限——英文句式、中文玩家名——记入 README 即可）。
- 回调接口：on_chat(player, message) / on_join(player) / on_leave(player) / on_advancement(player, adv) / on_death(player, message)。

### 2. 绑定存储（修订：直接写 AstrBot 配置项）
- **实现订正**（2026-10-23，实现阶段偏离此处原案）：原案是插件数据目录下 chat_bridge.json 原子写；
  实施时按项目 database-guidelines「不新增 data.json 存状态/配置」的条款，改为 `mc绑定` 命令直接写
  `unified_group_umo` 配置项 + `self.config.save_config()` 落盘。绑定关系即配置，配置面板可见可改，
  语义反而更一致。`unified_group_umo` 同时承担「绑定群」与「统一上下文目标群」两个角色。
- 加载时机：插件 __init__ 读文件；绑定/解绑命令即时读写。

### 3. 命令（main.py）
- `mc绑定`：仅 admin_ids 内用户；校验当前是群消息（event.get_message_type()）；取 event.unified_msg_origin 写入 chat_bridge.json；回复确认（含识别到的平台名）。
- `mc解绑`：同上，清除绑定。
- `mc喊话 <内容>`：需已启用 RCON；取 event.get_sender_name() 作昵称前缀；经 text_outbound 切段后 tellraw @a；频率保护：同一发送者 5s 冷却（内存字典即可）。
- 命令命名走 AstrBot 指令注册（@filter.command），与现有 mc_kb_rebuild 等一致。

### 4. 转发与统一上下文（main.py 改造）
- MC→QQ 转发：_forward_to_bound(text)：读绑定 UMO → context.send_message(umo, MessageChain().message(f"{prefix}{text}"))。mc_message_prefix 配置项在此真正生效（默认 "[MC]"）。发送失败仅 warning（含 qqofficial 群未发言场景）。
- 统一上下文：_send_fake_event 的 platform 参数从绑定 UMO 第一段取（`umo.split(":",1)[0]`），无绑定时回退 "aiocqhttp" 现状行为并 warning。系统事件注入上下文由新开关 enable_system_event_context（默认 false）控制；聊天注入沿用 enable_unified_context。
- 无绑定群时：转发跳过；统一上下文自动停用（warning 一次）。

### 5. RCON 出站文本（text_outbound.py 新增，纯函数）
- utf8 字节预算 1400/段切段（按字符边界切，不劈开多字节字符）；JSON 转义（引号/反斜杠）；拼 tellraw @a JSON。
- LLM 回复进游戏（_send_to_mc_chat 现有 200 字分段）改走同一切段逻辑，替换现有实现。
- 不处理 B6 旧版字符洗白（MC<1.9 不在本插件支持范围，务实裁剪）。

### 6. 配置 schema（_conf_schema.json）
- 删除：enable_log_monitor、log_server_host、log_server_port、log_reconnect_interval、log_max_reconnect_attempts。
- 保留：enable_chat_response、bot_nickname、enable_unified_context、unified_group_umo（语义改为初始绑定，可留空）、mc_message_prefix（R4 生效）。
- 新增：enable_system_event_context（bool，默认 false）。
- 旧配置文件里残留的已删 key 由 AstrBot 自然忽略，无需迁移代码。

### 7. 顺手修复（R8）
- rcon_client.py：删除 get_online_players 死代码；terminate() 中 await self.rcon.close()。

## 数据流

1. MC 玩家发言 → latest.log 追加 → LogWatcher 1s 内读到 → 解析 → on_chat → main.py：
   a. _forward_to_bound → QQ 群收到 "[MC] <Steve> xxx"（若已绑定）
   b. enable_unified_context 且已绑定 → 伪造事件注入该群会话 → 框架 wake_prefix 决定是否触发 LLM → 回复经 on_decorating_result 拦截 → RCON tellraw 回游戏（现状链路保留）。
2. QQ 群 `mc喊话 xxx` → 校验+冷却 → text_outbound 切段 → RCON tellraw @a "[QQ] 昵称: xxx"。
3. 系统事件 → on_join 等 → 转发绑定群；enable_system_event_context 时另注入上下文。

## 兼容性与回滚

- 配置：老配置多出的 key 无害；用户升级后聊天互通从「手动部署脚本」变「自动」，无迁移负担。
- 回滚：git revert 即可恢复旧双通道（log_server.py/log_client.py 在 git 历史中）。
- 风险与缓解：
  - qqofficial 群重启后未发言 → 主动推送失败 → 仅 warning + README 注明「机器人重启后群里任意发言一次即可恢复推送」。
  - 热重载幽灵任务 → 代际防护 + terminate cancel。
  - 日志高频刷屏 → 每轮最多读 1MiB、超限追尾（抄 Scintilla 阈值）。

## 明确不做（与 PRD Out of Scope 对齐）
异地降级、玩家绑定、群聊全量进游戏、MC mod、中文日志句式支持。
