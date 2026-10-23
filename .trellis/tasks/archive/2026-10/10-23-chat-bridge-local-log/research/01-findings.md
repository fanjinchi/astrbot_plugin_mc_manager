# 调研结论摘要（2026-10-23，三个并行子代理）

## A. 当前插件现状（astrbot_plugin_mc_manager）
- 出游戏：log_server.py（MC 主机独立脚本，tail latest.log → 裸 TCP+JSONL 推送）→ log_client.py（插件内，正则解析 <player> msg / join / leave / advancement / 死亡关键词）→ main.py:200-313 伪造 GroupMessage 事件进 AstrBot 管线。
- 进游戏：全部走 RCON tellraw @a（main.py:428-445）。log 通道只读单向。
- 痛点实锤：log_server.py 地址/端口/日志路径硬编码（含一个写死的 Windows 路径）；端口默认值自相矛盾（25571 vs 25576）；插件对 MC 启停零感知；伪造事件硬编码 platform="aiocqhttp"（main.py:252, 306）；mc_message_prefix 是死配置；rcon_client.py:111 get_online_players 调不存在方法（死代码）；terminate() 漏关 RCON。
- 可复用资产：mc_server_dir 配置已存在（kb 在用，kb/vanilla.py 已读 logs/latest.log 探测版本）；log_client.py 的正则集可直接搬迁；rcon_client.py 异步长连接+失败重连可继续用。

## B. 兄弟插件 Scintilla_MC_Server_Control（v0.24.7）
- 架构：同机本地轮询 <server_dir>/logs/latest.log（1s），正则解析 8 类事件 → StarTools.send_message(umo, chain) 推送；MC 服务端零侵入；异地时聊天互通整体禁用。
- log_watcher.py（1577 行）关键经验：
  - 轮询而非 inotify（Windows 兼容）；从文件尾起步不回溯。
  - 轮转四判据：文件变短（含半行缓冲）/ st_ino 变化 / 文件头 256B 指纹 / 64B 内容锚点；latest.log 缺失视为正常（服务器未启动），只计 missing_polls。
  - 文件 IO 走 daemon 单线程执行器（避免卡死事件循环、避免拖住进程退出）；单 IO 15s 超时+单飞；每轮最多读 1MiB，积压超 8MiB 追尾。
  - UTF-8/GBK 可读性评分嗅探；任务代际 _task_gen 防 AstrBot 热重载后旧任务复活。
  - 借鉴原则：抄防护思路，不必照搬全部 1500 行。
- mcs 桥接指令（main.py:2986-3018）：群内发指令自动捕获 event.unified_msg_origin 加为桥接目标——本任务 R3 的直接参照。
- text_outbound.py 实测结论：原版 RCON 读取缓冲 byte[1460]，超限服务端静默拔线；按 UTF-8 字节预算 1400 切段。B6：MC<1.9 全角括号吞字（本项目可不管）。
- player_bindings.py：原子写（tmp+replace）+失败回滚范式。
- 注意：Scintilla 的 QQ→MC 只有喊话指令无被动桥（与本任务决策一致）；其玩家名正则只认 [A-Za-z0-9_]{1,16}。

## C. AstrBot 框架能力
- QQ 官方机器人适配器存在：qq_official（WebSocket）与 qq_official_webhook，均注册于 astrbot/core/platform/sources/。
- 主动推送正确 API：context.send_message(umo_str, MessageChain)（astrbot/core/star/context.py:650）或 StarTools.send_message（star_tools.py:34-54）。按 UMO 第一段（平台实例 id）路由，平台无关。
- Context.send_message docstring 称「qq_official 不支持」是陈旧注释，与实现矛盾（qqofficial 已实现 send_by_session 且 support_proactive_message=True）。
- UMO 格式：{platform_id}:{GroupMessage|FriendMessage}:{session_id}。aiocqhttp 群 session_id=群号；qq_official 群 session_id=group_openid（只能从收到的群消息获得 → 群内绑定命令天然解决）。
- qq_official 主动群推送限制：目标群需在机器人本次运行中至少发言一次（建立 scene/msg_id 缓存），否则落入频道分支发送失败（仅 warning）；腾讯主动消息配额框架不管，插件需克制频率并容错。
- 后台任务推送范例：dailyhub / piconnector / monixiuxian / Scintilla 均用 context.send_message 或 StarTools.send_message。
- mc_manager 出向已平台无关（main.py:661）；需改的是入向伪造事件的 platform 硬编码 → 从绑定群 UMO 第一段取 platform_id 传给 StarTools.create_event。
