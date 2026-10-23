# 聊天互通重构：本地日志直连+群绑定命令+平台解耦

## Goal

废弃独立的 log_server.py 脚本及其 TCP 通道，改为插件内直接 tail `mc_server_dir/logs/latest.log` 实现 MC↔QQ 聊天互通；检测到 MC 服务器启动后自动接管，全程无需用户手动部署或配置额外地址；QQ 群内发命令即可绑定/解绑目标群（免手抄 UMO，平台无关，支持 onebot 与 QQ 官方机器人）；新增喊话命令从 QQ 向 MC 传话。

## Context / 前提

- 部署形态已确认：**AstrBot 与 MC 服务端同机**，`mc_server_dir` 配置项用户已为物品知识库填好，可直接推出 `logs/latest.log` 路径。
- QQ→MC 方向维持现状语义：群里普通聊天**不**自动转发进游戏；只有 LLM 回复（现状）和新增的喊话命令会进游戏。
- 不做玩家绑定（QQ↔MC 游戏名映射）。
- 统一上下文功能保留，但实现做平台无关简化（详见 R6）。
- 参考实现：同目录兄弟插件 astrbot_plugin_Scintilla_MC_Server_Control 的 log_watcher（本地轮询+轮转检测）、mcs 桥接（群内命令自绑定 UMO）、text_outbound（RCON 字节预算）。

## Requirements

- R1 通道重构：删除 `log_server.py`、`log_client.py` 及配套配置项（log_server_host / log_server_port / log_reconnect_interval / log_max_reconnect_attempts / enable_log_monitor 的 TCP 语义）；新增插件内日志监听器，直接读取 `mc_server_dir/logs/latest.log`，沿用现有正则解析玩家聊天。
- R2 自动感知与接管：插件启动后以后台任务自动工作——`mc_server_dir` 已配置时无需任何开关即开始监视；latest.log 出现/服务器重启（文件轮转）时自动恢复监听，不丢监听恢复之后的消息；日志文件缺失（服务器未启动）时静默等待，不报错刷屏。
- R3 群绑定命令：群管理员在目标 QQ 群发送绑定命令（如 `mc绑定`），插件捕获 `event.unified_msg_origin` 存为转发目标并即时生效；提供解绑命令。不依赖任何特定平台适配器（onebot / qq_official / qq_official_webhook 均可用）。
- R4 消息转发（MC→QQ）：系统事件（进服/退服/死亡/成就）直接推送到绑定群；玩家聊天需以可配置前缀（mc_bridge_prefix，默认 mc喊话，留空=全转）开头才转发（2026-10-23 按用户反馈修订：双向都是显式传话），消息带可区分来源的前缀；发送走 `context.send_message` 平台无关通道；`mc_message_prefix` 配置项真正生效或删除（二选一，不留死配置）。
- R5 喊话命令（QQ→MC）：新增命令（如 `mc喊话 <内容>`）经 RCON `tellraw` 把消息送进 MC 聊天，带发送者 QQ 昵称前缀；必须处理 RCON 单包 1460 字节限制（超限切段或拒绝并提示），避免中文长文本被服务端静默拔线；带基本频率/长度保护。
- R6 统一上下文简化：保留「MC 聊天注入绑定群 LLM 会话上下文」能力，但伪造事件的 platform 不再硬编码 aiocqhttp，改为从绑定群 UMO 第一段取；系统事件是否注入上下文做成独立开关；无绑定群时该功能自动停用。
- R7 配置精简：插件配置中不再出现 log 通道相关项；聊天互通所需配置收敛为 `mc_server_dir`（已有）+ RCON 三件套（已有）+ 群内命令绑定，用户无需手抄 UMO。
- R8 顺手修复（小）：rcon_client.py 的 `get_online_players` 死代码（调用了不存在的方法）删除或修复；`terminate()` 补上 RCON 连接关闭。

## Out of Scope

- 异地部署（AstrBot 与 MC 不同机）的聊天互通——本次直接放弃，不保留 log_server.py 降级。
- 玩家绑定（QQ↔MC 游戏名）。
- 群内普通聊天自动转发进游戏（维持现状，仅 LLM 回复与喊话命令进游戏）。
- MC 服务端 mod/插件开发。
- 日志解析对中文服务端/非英文日志句式的支持（与现状一致，不退步即可）。

## Acceptance Criteria

- [ ] AC1：仅配置 `mc_server_dir` + RCON 三件套（不填任何日志通道地址），启动 MC 服务器后插件自动开始监听，游戏内发言无需任何额外操作即可被插件捕获。
- [ ] AC2：在 QQ 群发送绑定命令后，该群能收到 MC 系统事件（进/退服、死亡、成就）推送，以及以 `mc_bridge_prefix` 开头（默认 `mc喊话`）的玩家聊天；解绑后停止。
- [ ] AC3：在 QQ 群发送喊话命令，消息带昵称前缀出现在 MC 游戏内聊天；超长中文消息不被静默丢弃（切段送达或明确拒绝提示）。
- [ ] AC4：MC 服务器停止→重启后，监听自动恢复，重启完成后的聊天/事件正常转发，无需重启 AstrBot 或重载插件。
- [ ] AC5：配置项中不再存在 log_server_host/log_server_port 等 TCP 通道配置；插件目录中不再存在 log_server.py。
- [ ] AC6：消息推送路径不硬编码任何平台适配器名称；代码层面 aiocqhttp 与 qq_official 走同一通道（官方机器人环境实测或明确记录实测限制）。
- [ ] AC7：统一上下文开启且有绑定群时，MC 聊天进入该群 LLM 会话历史；伪造事件不再硬编码 aiocqhttp。

## Notes

- 关键风险：RCON 单包 1460B（中文 tellraw 必切段）；日志轮转检测（inode/变短/文件头指纹）；AstrBot 热重载下后台任务的幽灵任务问题（兄弟插件有现成防护经验）。
- 官方 QQ 机器人已知限制：群 id 为 group_openid（绑定命令天然解决）；目标群需在机器人启动后至少发言一次才能稳定主动推送；主动消息有腾讯配额，推送需克制。
