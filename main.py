"""
AstrBot MC服务器管理插件
通过LLM智能管理Minecraft服务器，支持Fabric/Forge/NeoForge
"""

import asyncio
import os
import time
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api import AstrBotConfig, logger
from astrbot.core.provider.entities import LLMResponse

from .rcon_client import MinecraftRCON
from .tools import game_tools, server_tools, world_tools
from .log_watcher import LogWatcher
from .text_outbound import build_tellraw_commands
from .runtime_dump import RuntimeDumpRunner
from .kb import KnowledgeBase
from .kb import commands as cmd_kb


# _send_fake_event / _send_system_event 伪造事件的 self_id：用于识别“来自 MC 聊天”的伪造事件，
# 防止游戏内聊天触发 QQ 侧的绑定/喊话命令
FAKE_EVENT_SELF_ID = "astrbot_mc_plugin"


@register(
    name="mc_manager",
    desc="通过LLM智能管理Minecraft服务器",
    version="1.0.0",
    author="AstrBot Community"
)
class MCManagerPlugin(Star):
    """Minecraft服务器管理插件"""
    
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        
        # 从配置加载RCON设置
        self.config = config
        
        # 初始化RCON客户端
        self.rcon = MinecraftRCON(
            host=self.config.get("rcon_host", "localhost"),
            port=self.config.get("rcon_port", 25575),
            password=self.config.get("rcon_password", "")
        )
        
        # 加载管理员列表
        self.admin_ids = set(self.config.get("admin_ids", []))
        
        # 是否启用危险命令
        self.enable_dangerous = self.config.get("enable_dangerous_commands", False)
        
        # 是否允许普通玩家（非管理员）使用 give_item
        self.enable_public_give_item = self.config.get("enable_public_give_item", False)
        
        # 唤醒词配置已移除 - 所有消息都提交，由AstrBot框架层唤醒词决定是否调用LLM
        # 旧配置: self.wake_words = self.config.get("wake_words", ["bot"])
        
        # 是否启用聊天响应
        self.enable_chat_response = self.config.get("enable_chat_response", True)
        
        # 加载机器人昵称配置
        self.bot_nickname = self.config.get("bot_nickname", "Bot")
        
        # 加载统一上下文配置
        # unified_group_umo 同时作为「绑定群」：mc绑定 命令会改写并保存它
        self.enable_unified_context = self.config.get("enable_unified_context", False)
        self.unified_group_umo = self.config.get("unified_group_umo", "")
        self.mc_message_prefix = self.config.get("mc_message_prefix", "[MC]")
        # 系统事件（进/退服、死亡、成就）注入 LLM 会话上下文的开关
        self.enable_system_event_context = self.config.get("enable_system_event_context", False)
        # 系统事件是否推送到绑定群（默认开；只影响群推送，不影响上下文注入）
        self.enable_system_event_forward = self.config.get("enable_system_event_forward", True)
        # 游戏内聊天转发到绑定群的前缀（默认 mc喊话，留空=全部转发）；系统事件转发不受此前缀控制
        self.mc_bridge_prefix = self.config.get("mc_bridge_prefix", "mc喊话")
        
        # 物品知识库配置（默认值须与 _conf_schema.json 一致）
        self.mc_server_dir = self.config.get("mc_server_dir", "")
        self.mc_version = self.config.get("mc_version", "")
        self.mc_client_dir = self.config.get("mc_client_dir", "")
        self.vanilla_zh_download = self.config.get("vanilla_zh_download", True)
        self.cfpa_auto_download = self.config.get("cfpa_auto_download", True)
        
        # 物品知识库（mods/ 的派生缓存，数据目录 = AstrBot/data/plugin_data/astrbot_plugin_mc_manager）
        self.kb = None
        try:
            from astrbot.core.star.star_tools import StarTools
            self.kb = KnowledgeBase(
                data_dir=StarTools.get_data_dir("astrbot_plugin_mc_manager"),
                server_dir=self.mc_server_dir,
                mc_version=self.mc_version,
                client_dir=self.mc_client_dir,
                vanilla_zh_download=self.vanilla_zh_download,
                cfpa_auto_download=self.cfpa_auto_download,
            )
        except Exception as e:
            logger.warning(f"物品知识库初始化失败（不影响其他功能）: {e}")
        
        # 初始化日志监听器（同机直连 latest.log，无需独立脚本，无需开关：
        # 配了 mc_server_dir 就自动工作；服务器启动/重启由 watcher 自动感知）
        self.log_watcher = None
        self._watcher_log_path = ""
        if self.mc_server_dir:
            self._watcher_log_path = os.path.join(self.mc_server_dir, "logs", "latest.log")
            self.log_watcher = LogWatcher(self._watcher_log_path)
            self.log_watcher.set_chat_callback(self._on_mc_chat)
            self.log_watcher.set_player_join_callback(self._on_player_join)
            self.log_watcher.set_player_leave_callback(self._on_player_leave)
            self.log_watcher.set_player_advancement_callback(self._on_player_advancement)
            self.log_watcher.set_player_death_callback(self._on_player_death)
        
        # mc喊话 的按人冷却（发送者ID -> 上次发送的 monotonic 时间）
        self._shout_cooldown: dict[str, float] = {}
        
        # 运行时 dump 单飞锁：dump 期间不允许第二次并发触发（避免双份导出/RCON 响应串包）
        self._dump_lock = asyncio.Lock()
        
        # 注入RCON客户端到所有工具模块
        self._inject_rcon()
        
        logger.info(f"MC Manager插件已加载，RCON: {self.config.get('rcon_host')}:{self.config.get('rcon_port')}")
    
    async def initialize(self):
        """插件激活时自动调用 - 启动日志监听（检测到服务器启动后自动接管）"""
        if self.log_watcher:
            await self.log_watcher.start()
        else:
            logger.warning("未配置 mc_server_dir，MC聊天监听与物品知识库不可用")
    
    def _inject_rcon(self):
        """将RCON客户端注入到所有工具模块"""
        game_tools.set_rcon(self.rcon)
        server_tools.set_rcon(self.rcon)
        server_tools.set_dangerous_commands_enabled(self.enable_dangerous)
        world_tools.set_rcon(self.rcon)
    
    async def _on_mc_chat(self, player: str, message: str):
        """
        玩家聊天回调：按前缀转发到绑定群 + 注入 AstrBot 事件管线（LLM 游戏内响应依赖）
        
        Args:
            player: 玩家名称
            message: 聊天消息内容
        """
        # MC→QQ 是显式传话：只有以前缀开头的游戏内消息才转发进群（对称于QQ侧的 mc喊话 命令）
        forward_text = message
        if self.mc_bridge_prefix:
            if not message.startswith(self.mc_bridge_prefix):
                forward_text = ""
            else:
                forward_text = message[len(self.mc_bridge_prefix):].strip()
        if forward_text:
            await self._forward_to_bound_group(f"<{player}> {forward_text}")
        # 伪造事件提交进事件管线：由框架 wake_prefix 决定是否触发 LLM（不受转发前缀影响）
        await self._send_fake_event(player, message)
    
    def _bound_platform_id(self) -> str:
        """取伪造事件要挂到的平台实例 id（UMO 格式: 平台ID:消息类型:会话ID）。

        优先绑定群的平台；无绑定时从当前已加载的平台实例里挑第一个
        （纯 QQ官方机器人 部署下硬编码 aiocqhttp 会让 create_event 找不到平台），
        一个平台都没有时回退 aiocqhttp 字符串（会被上层 try/except 吞掉并记日志）。
        """
        parts = self.unified_group_umo.split(":", 2) if self.unified_group_umo else []
        if len(parts) == 3 and parts[0]:
            return parts[0]
        try:
            insts = self.context.platform_manager.platform_insts
            if insts:
                return insts[0].meta().id
        except Exception:
            pass
        return "aiocqhttp"

    @staticmethod
    def _is_mc_fake_event(event: AstrMessageEvent) -> bool:
        """是否为插件从 MC 聊天伪造的事件（这类事件不允许触发 QQ 侧命令）"""
        return event.get_self_id() == FAKE_EVENT_SELF_ID
    
    async def _forward_to_bound_group(self, text: str):
        """
        把 MC 侧消息推送到绑定群（平台无关，走 context.send_message 按 UMO 路由）
        
        Args:
            text: 消息内容（会自动加上 mc_message_prefix 前缀）
        """
        if not self.unified_group_umo:
            return
        try:
            from astrbot.api.event import MessageChain
            chain = MessageChain().message(f"{self.mc_message_prefix} {text}")
            ok = await self.context.send_message(self.unified_group_umo, chain)
            if not ok:
                logger.warning("转发MC消息到绑定群失败：未找到匹配的消息平台（绑定群所在平台可能未加载）")
        except Exception as e:
            # QQ官方机器人主动推送有配额/群发言前提等限制，失败仅记日志不打断监听
            logger.error(f"转发MC消息到绑定群失败: {e}")
    
    async def _forward_system_event(self, text: str):
        """系统事件转发到绑定群（受 enable_system_event_forward 控制；与上下文注入开关独立）"""
        if self.enable_system_event_forward:
            await self._forward_to_bound_group(text)
    
    async def _on_player_join(self, player: str):
        """
        玩家登入事件回调
        
        Args:
            player: 玩家名称
        """
        logger.info(f"[MC事件] 玩家 {player} 加入了游戏")
        await self._forward_system_event(f"玩家 {player} 加入了游戏")
        if self.enable_system_event_context:
            await self._send_system_event(player, f"[系统消息] {player} 加入了游戏")
    
    async def _on_player_leave(self, player: str):
        """
        玩家登出事件回调
        
        Args:
            player: 玩家名称
        """
        logger.info(f"[MC事件] 玩家 {player} 离开了游戏")
        await self._forward_system_event(f"玩家 {player} 离开了游戏")
        if self.enable_system_event_context:
            await self._send_system_event(player, f"[系统消息] {player} 离开了游戏")
    
    async def _on_player_advancement(self, player: str, advancement: str):
        """
        玩家达成成就事件回调
        
        Args:
            player: 玩家名称
            advancement: 成就名称
        """
        logger.info(f"[MC事件] 玩家 {player} 达成了成就 [{advancement}]")
        await self._forward_system_event(f"玩家 {player} 达成了成就 [{advancement}]")
        if self.enable_system_event_context:
            await self._send_system_event(player, f"[系统消息] {player} 达成了成就 [{advancement}]")
    
    async def _on_player_death(self, player: str, reason: str):
        """
        玩家死亡事件回调
        
        Args:
            player: 玩家名称
            reason: 死因描述
        """
        logger.info(f"[MC事件] 玩家死亡: {reason}")
        await self._forward_system_event(reason)
        if self.enable_system_event_context:
            await self._send_system_event(player, f"[系统消息] {reason}")
    
    async def _send_fake_event(self, player: str, message: str):
        """
        提交所有MC消息到AstrBot
        - LTM会记录所有消息作为上下文
        - 只有包含AstrBot配置的唤醒词的消息才会触发LLM
        
        Args:
            player: 玩家名称
            message: 消息内容
        """
        try:
            from astrbot.core.star.star_tools import StarTools
            from astrbot.core.message.components import Plain
            from astrbot.core.platform.astrbot_message import MessageMember
            
            # 如果启用了统一上下文且配置了UMO，从UMO中提取session_id
            # 否则使用默认的 "mc_server_chat"
            if self.enable_unified_context and self.unified_group_umo:
                # UMO格式: platform_id:message_type:session_id
                parts = self.unified_group_umo.split(":")
                mc_session_id = parts[2] if len(parts) == 3 else "mc_server_chat"
                group_id = mc_session_id
            else:
                mc_session_id = "mc_server_chat"
                group_id = "mc_server_chat"
            
            # 使用真实的玩家信息
            sender = MessageMember(
                user_id=f"mc_player_{player}",  # 用玩家名作为ID
                nickname=f"{player}(MC)"  # 显示玩家名和来源
            )
            
            # 直接使用原始消息,不添加前缀,保证唤醒词能正常识别
            # LTM会自动记录发送者昵称,LLM能从对话历史看到是MC玩家
            message_text = message
            
            # 创建新消息对象
            new_message = await StarTools.create_message(
                type="GroupMessage",
                self_id=FAKE_EVENT_SELF_ID,
                session_id=mc_session_id,
                sender=sender,
                message=[Plain(message_text)],
                message_str=message_text,
                group_id=group_id
            )
            
            # 提交事件到AstrBot
            # - is_wake=False 让框架根据唤醒词配置决定是否调用LLM
            # - LTM仍然会记录所有消息作为上下文
            # - platform 取绑定群的平台实例 id，保证非 onebot 平台（如QQ官方机器人）下
            #   统一上下文会话落在正确的适配器上
            await StarTools.create_event(
                abm=new_message,
                platform=self._bound_platform_id(),
                is_wake=False
            )
            
            logger.info(f"MC消息已提交: [{player}] {message}")
            
        except Exception as e:
            logger.error(f"提交MC消息失败: {e}")
    
    async def _send_system_event(self, player: str, event_message: str):
        """
        伪造MC系统事件提交到AstrBot
        - 用于上报登入、登出、成就、死亡等系统事件
        - LTM会记录所有事件作为上下文
        - 系统事件默认不会触发LLM，但LLM能在对话历史中看到
        
        Args:
            player: 相关玩家名称
            event_message: 事件消息内容
        """
        try:
            from astrbot.core.star.star_tools import StarTools
            from astrbot.core.message.components import Plain
            from astrbot.core.platform.astrbot_message import MessageMember
            
            # 使用相同的session_id确保上下文连续
            if self.enable_unified_context and self.unified_group_umo:
                parts = self.unified_group_umo.split(":")
                mc_session_id = parts[2] if len(parts) == 3 else "mc_server_chat"
                group_id = mc_session_id
            else:
                mc_session_id = "mc_server_chat"
                group_id = "mc_server_chat"
            
            # 系统消息使用特殊的sender标识
            sender = MessageMember(
                user_id="mc_system",  # 系统消息ID
                nickname="MC服务器"  # 显示为服务器
            )
            
            # 创建系统消息对象
            new_message = await StarTools.create_message(
                type="GroupMessage",
                self_id=FAKE_EVENT_SELF_ID,
                session_id=mc_session_id,
                sender=sender,
                message=[Plain(event_message)],
                message_str=event_message,
                group_id=group_id
            )
            
            # 提交事件到AstrBot（不触发唤醒，但会记录到LTM）
            await StarTools.create_event(
                abm=new_message,
                platform=self._bound_platform_id(),
                is_wake=False
            )
            
            logger.info(f"MC系统事件已提交: {event_message}")
            
        except Exception as e:
            logger.error(f"提交MC系统事件失败: {e}")
    
    
    async def terminate(self):
        """插件禁用/重载时自动调用 - 清理资源"""
        # 物品知识库按"连接即用即关"实现（store.py），没有需要关闭的长连接
        # 停止日志监听（含 daemon IO 线程与事件循环任务）
        if self.log_watcher:
            await self.log_watcher.stop()
        # 关闭 RCON 长连接（旧版漏关，靠 __del__ 兜底）
        await self.rcon.close()
    
    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, response: LLMResponse):
        """
        LLM响应后的钩子 - 已由on_decorating_result统一处理MC消息回复
        保留此钩子以防未来需要特殊处理LLM响应
        
        Args:
            event: 原始消息事件
            response: LLM的响应
        """
        pass
    
    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        """
        装饰结果钩子,用于:
        1. 检测MC消息是否匹配了指令,如果是则标记为已发送以跳过LLM
        2. 拦截MC消息的所有回复并发送到MC聊天框
        
        Args:
            event: 消息事件
        """
        # 检查是否是MC玩家的消息
        sender_id = event.get_sender_id()
        if sender_id and sender_id.startswith("mc_player_"):
            # 检查是否有其他插件的handler被激活(表示匹配了指令)
            activated_handlers = event.get_extra("activated_handlers", default=[])
            for handler in activated_handlers:
                # 排除本插件的handler
                if not handler.handler_module_path.startswith("astrbot_plugin_mc_manager"):
                    logger.info(f"MC消息匹配了指令 {handler.handler_full_name}，标记为已发送操作以跳过LLM")
                    # 标记为已有发送操作，让process_stage跳过LLM调用
                    event._has_send_oper = True
                    break
            
            # 获取回复内容
            result = event.get_result()
            if result and result.chain:
                # 提取纯文本内容
                try:
                    from astrbot.core.message.message_event_result import MessageChain
                    message_chain = MessageChain(result.chain)
                    response_text = message_chain.get_plain_text()
                    
                    # 过滤掉Agent多轮调用时的中间响应
                    # *No response* 是Agent在工具调用过程中的占位符，不应该发送到MC
                    if response_text and self.enable_chat_response:
                        # 检查是否是无效响应
                        if response_text.strip() not in ["*No response*", ""]:
                            # 发送到MC聊天框
                            await self._send_to_mc_chat(response_text)
                        else:
                            logger.debug(f"过滤掉中间响应: {response_text}")
                except Exception as e:
                    logger.error(f"提取MC回复内容失败: {e}")
                
                # 清空消息链,阻止发送到QQ群
                result.chain = []
    
    async def _send_to_mc_chat(self, message: str):
        """
        将消息发送到MC服务器聊天框（按 RCON 单包字节预算切段，防止中文长文本被静默拔线）
        
        Args:
            message: 要发送的消息内容
        """
        prefix = f"[{self.bot_nickname}] "
        for command in build_tellraw_commands(message, prefix=prefix, color="aqua"):
            try:
                result = await self.rcon.execute_async(command)
                # execute_async 永远不抛，失败返回 "错误:" 前缀字符串
                if result.startswith("错误:"):
                    logger.error(f"发送消息到MC聊天框失败: {result}")
                    break
            except Exception as e:
                logger.error(f"发送消息到MC聊天框失败: {e}")
                break
    
    def is_admin(self, user_id: str) -> bool:
        """
        检查用户是否为管理员
        
        Args:
            user_id: 用户ID（QQ号或MC玩家ID，格式：mc_player_{玩家名}）
            
        Returns:
            是否为管理员，如果admin_ids为空则所有人都是管理员
        """
        logger.info(f"权限检查: user_id={user_id}, admin_ids={self.admin_ids}")
        if not self.admin_ids:
            return True
        
        # 检查原始ID（QQ号）
        if str(user_id) in self.admin_ids:
            return True
        
        # 检查MC玩家名（从 mc_player_PlayerName 提取 PlayerName）
        if user_id.startswith("mc_player_"):
            player_name = user_id.replace("mc_player_", "")
            if player_name in self.admin_ids:
                return True
        
    
    def _check_permission(self, event: AstrMessageEvent) -> tuple[bool, str]:
        """
        检查用户是否有权限执行操作
        
        Args:
            event: 消息事件
            
        Returns:
            (是否有权限, 错误消息或空字符串)
        """
        user_id = event.get_sender_id()
        if not self.is_admin(user_id):
            return False, f"权限不足：用户 {user_id} 不在管理员列表中"
        return True, ""

    @filter.llm_tool(name="give_item")
    async def tool_give_item(self, event: AstrMessageEvent, player: str, item: str, count: int = 1) -> str:
        """给予玩家物品
        
        Args:
            player(string): 要给予物品的玩家名称
            item(string): 物品ID，如diamond、iron_sword；模组物品用完整ID，如 create:brass_ingot
            count(number): 物品数量，默认1
        """
        # 配置 enable_public_give_item 开启时，普通玩家也可使用（免权限）
        if not self.enable_public_give_item:
            has_permission, error_msg = self._check_permission(event)
            if not has_permission:
                return error_msg
        return await game_tools.give_item(player, item, count)
    
    @filter.llm_tool(name="teleport_player")
    async def tool_teleport_player(self, event: AstrMessageEvent, player: str, target: str) -> str:
        """传送玩家
        
        Args:
            player(string): 要传送的玩家名称
            target(string): 目标位置（坐标如"100 64 200"）或目标玩家名称
        """
        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            return error_msg
        return await game_tools.teleport_player(player, target)
    
    @filter.llm_tool(name="set_gamemode")
    async def tool_set_gamemode(self, event: AstrMessageEvent, player: str, mode: str) -> str:
        """设置玩家游戏模式
        
        Args:
            player(string): 玩家名称
            mode(string): 游戏模式：survival/creative/adventure/spectator
        """
        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            return error_msg
        return await game_tools.set_gamemode(player, mode)
    
    @filter.llm_tool(name="list_players")
    async def tool_list_players(self, event: AstrMessageEvent) -> str:
        """获取在线玩家列表（无需权限）"""
        return await server_tools.list_players()
    
    @filter.llm_tool(name="tellraw")
    async def tool_tellraw(self, event: AstrMessageEvent, message: str, sender: str = "Bot", color: str = "yellow", target: str = "@a") -> str:
        """通过tellraw在游戏公屏发送聊天消息
        
        Args:
            message(string): 要发送的消息内容
            sender(string): 发送者名称，默认为"Bot"
            color(string): 消息颜色，可选值：yellow/red/green/blue/white/gold/aqua/dark_red等，默认为yellow
            target(string): 目标玩家，默认@a（所有玩家）
        """
        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            return error_msg
        return await server_tools.tellraw(message, sender, color, target)
    
    @filter.llm_tool(name="execute_command")
    async def tool_execute_command(self, event: AstrMessageEvent, command: str) -> str:
        """执行任意Minecraft命令的通用工具（管理员）
        
        踢人/封禁/白名单/难度/游戏规则/标题/保存世界等没有专用工具的操作都通过它执行。
        不确定命令名称或参数写法时，先用 search_mc_commands 查询用法再调用本工具。
        
        Args:
            command(string): 要执行的命令（不需要/前缀）
        """
        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            return error_msg
        return await server_tools.execute_command(command)
    
    @filter.llm_tool(name="set_weather")
    async def tool_set_weather(self, event: AstrMessageEvent, weather_type: str, duration: int = None) -> str:
        """设置天气
        
        Args:
            weather_type(string): clear/rain/thunder
            duration(number): 可选，持续时间（秒）
        """
        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            return error_msg
        return await world_tools.set_weather(weather_type, duration)
    
    @filter.llm_tool(name="set_time")
    async def tool_set_time(self, event: AstrMessageEvent, time_value: str) -> str:
        """设置时间
        
        Args:
            time_value(string): 时间值，如day/noon/night/midnight或具体数字
        """
        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            return error_msg
        return await world_tools.set_time(time_value)
    
    @filter.llm_tool(name="summon_entity")
    async def tool_summon_entity(self, event: AstrMessageEvent, entity: str, x: float = None, y: float = None, z: float = None) -> str:
        """生成实体
        
        Args:
            entity(string): 实体类型，如zombie；模组实体用完整ID，如 iceandfire:fire_dragon
            x(number): X坐标
            y(number): Y坐标
            z(number): Z坐标
        """
        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            return error_msg
        return await world_tools.summon_entity(entity, x, y, z)
    
    @filter.llm_tool(name="search_mc_items")
    async def tool_search_mc_items(self, event: AstrMessageEvent, keyword: str, limit: int = 10) -> str:
        """搜索MC物品/方块/实体知识库（无需权限）
        
        在已构建的物品知识库里按中文名、英文名或完整ID模糊搜索，返回可直接使用的完整ID
        （给物品用 give_item、生成实体用 summon_entity、填方块用 execute_command 的 fill）、
        中英文名、所属模组和类型。玩家只说物品俗名/中文名、或你不确定模组ID时先用它查。
        
        Args:
            keyword(string): 搜索关键词，如「黄铜锭」「brass_ingot」「diamond_sword」
            limit(number): 最多返回条数，默认10
        """
        if self.kb is None:
            return "物品知识库不可用（插件数据目录初始化失败），请查看日志"
        return self.kb.search(keyword, limit)
    
    @filter.llm_tool(name="search_mc_commands")
    async def tool_search_mc_commands(self, event: AstrMessageEvent, keyword: str, limit: int = 8) -> str:
        """搜索MC命令用法（无需权限）
        
        在内置原版命令知识库和服务器导出的运行时命令快照里，按命令名、中文描述或参数语法模糊搜索，
        返回命令语法、说明和权限等级（运行时条目的权限显示为未知）。运行时语法来自服务端当前命令树（已注册路径不代表当前调用者必然可执行；
        RCON help 回退快照的深层分支是压缩语法）。准备调用 execute_command 但不确定命令怎么写时先用它查。
        
        关键词写法很重要：内置原版命令有中文描述，可以直接用中文（「封禁」）；模组命令只有英文命令名和
        参数语法，没有中文说明，中文意图要自己先提炼成一两个简短英文概念词（「陈酿」→ wine、
        「传送石碑」→ waystone、「清辐射」→ radiation removeAll），不要直接搜整句中文。
        多个英文词用空格隔开即可，顺序不限、会同时要求命中同一根（quest editing 等价 editing quest）；
        channel mode / channel_mode / channel-mode 都能命中 channelmode。没命中就换更短的词或英文近义
        说法，命中根后再用子命令/参数词细化（「只看某个子命令怎么写」也用它）。
        
        Args:
            keyword(string): 搜索关键词：原版命令可用中文描述，模组命令用英文词，如「封禁」「weather」「waystone list」
            limit(number): 最多返回条数（按根命令计数），默认8
        """
        data_dir = self.kb.data_dir if self.kb is not None else None
        return cmd_kb.search_commands(keyword, limit, data_dir=data_dir)
    
    @filter.llm_tool(name="send_to_qq_group")
    async def tool_send_to_qq_group(self, event: AstrMessageEvent, message: str) -> str:
        """向绑定的QQ群发送消息
        
        当MC玩家发送消息触发LLM时，LLM的回复默认只会在MC中显示。
        使用此工具可以将消息同时发送到绑定的QQ群，让QQ群成员也能看到。
        
        Args:
            message(string): 要发送到QQ群的消息内容
        """
        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            return error_msg
        
        # 检查是否已绑定QQ群
        if not self.unified_group_umo:
            return "❌ 未绑定QQ群（管理员在目标群发送 mc绑定 即可绑定），无法发送"
        
        try:
            from astrbot.api.event import MessageChain
            
            # 构造消息链
            message_chain = MessageChain().message(message)
            
            # 使用配置的UMO字符串直接发送
            await self.context.send_message(self.unified_group_umo, message_chain)
            
            return f"✓ 已发送到QQ群"
            
        except Exception as e:
            logger.error(f"发送消息到QQ群失败: {e}")
            return f"❌ 发送到QQ群失败: {str(e)}"

    # 工具已通过 @filter.llm_tool 装饰器自动注册到AstrBot
    # 用户直接与LLM对话时，LLM会自动识别并调用这些MC管理工具
    # 无需命令前缀，直接说"查看在线玩家"、"踢出Steve"等即可
    
    @filter.command("test_connection")
    async def test_connection(self, event: AstrMessageEvent):
        '''测试MC服务器RCON连接状态'''
        logger.info("触发test_connection指令，正在测试RCON连接...")
        
        try:
            success, message = await self.rcon.test_connection_async()
            if success:
                result = f"✓ RCON连接成功\n服务器: {self.config.get('rcon_host')}:{self.config.get('rcon_port')}\n{message}"
                logger.info(f"RCON连接测试成功: {message}")
            else:
                result = f"✗ RCON连接失败\n服务器: {self.config.get('rcon_host')}:{self.config.get('rcon_port')}\n原因: {message}"
                logger.warning(f"RCON连接测试失败: {message}")
        except Exception as e:
            result = f"✗ RCON连接测试出错\n错误: {str(e)}"
            logger.error(f"RCON连接测试出错: {str(e)}")
        
        yield event.plain_result(result)

    @filter.command("test_log")
    async def cmd_test_log_connection(self, event: AstrMessageEvent):
        """查看本地日志监听状态（latest.log 直连）"""
        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            yield event.plain_result(error_msg)
            return
        
        if not self.log_watcher:
            yield event.plain_result("日志监听不可用：未配置 mc_server_dir（MC 服务器根目录）")
            return
        
        yield event.plain_result(self.log_watcher.status_text())

    @filter.command("mc绑定")
    async def cmd_bind_group(self, event: AstrMessageEvent):
        """把当前QQ群绑定为MC消息转发目标（管理员）"""
        if self._is_mc_fake_event(event):
            yield event.plain_result("❌ 该命令只能在QQ群内使用")
            return

        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            yield event.plain_result(error_msg)
            return
        
        if not event.get_group_id():
            yield event.plain_result("❌ 请在目标QQ群里使用本命令")
            return
        
        # 自动捕获当前会话 UMO，免手抄，且天然适配任意平台（onebot/QQ官方机器人等）
        umo = event.unified_msg_origin
        self.config["unified_group_umo"] = umo
        self.unified_group_umo = umo
        try:
            self.config.save_config()
        except Exception as e:
            logger.error(f"保存群绑定配置失败: {e}")
            yield event.plain_result(f"❌ 绑定已生效但保存配置失败（重启后失效）: {e}")
            return
        
        bridge_hint = (
            f"游戏内以 {self.mc_bridge_prefix} 开头的聊天"
            if self.mc_bridge_prefix
            else "游戏内聊天"
        )
        if self.enable_system_event_forward:
            push_desc = f"{bridge_hint}与系统事件将推送到本群"
        else:
            push_desc = f"{bridge_hint}将推送到本群（系统事件推送已在配置中关闭）"
        yield event.plain_result(
            f"✓ 已绑定本群为MC消息转发目标（平台: {event.get_platform_name()}）\n"
            f"{push_desc}；发送 mc解绑 可解除。"
        )

    @filter.command("mc解绑")
    async def cmd_unbind_group(self, event: AstrMessageEvent):
        """解除MC消息转发群的绑定（管理员）"""
        if self._is_mc_fake_event(event):
            yield event.plain_result("❌ 该命令只能在QQ群内使用")
            return

        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            yield event.plain_result(error_msg)
            return
        
        if not self.unified_group_umo:
            yield event.plain_result("当前没有绑定任何群")
            return
        
        self.config["unified_group_umo"] = ""
        self.unified_group_umo = ""
        try:
            self.config.save_config()
        except Exception as e:
            logger.error(f"保存群绑定配置失败: {e}")
            yield event.plain_result(f"❌ 解绑已生效但保存配置失败（重启后恢复）: {e}")
            return
        
        yield event.plain_result("✓ 已解除群绑定，MC消息不再转发到QQ群")

    @filter.command("mc喊话")
    async def cmd_shout_to_mc(self, event: AstrMessageEvent):
        """把消息发送到MC游戏内聊天（限绑定群，同一人 5 秒冷却）"""
        # 喊话是聊天桥的一部分，只在绑定群可用，避免 bot 所在任意群都能往公屏说话；
        # 同时拒绝 MC 聊天伪造的事件，避免游戏内 #mc喊话 被当成群喊话再 tellraw 回游戏
        if self._is_mc_fake_event(event):
            yield event.plain_result("❌ 该命令只能在QQ群内使用")
            return
        if not self.unified_group_umo:
            yield event.plain_result("❌ 未绑定MC互通群，请管理员先在目标群发送 mc绑定")
            return
        if event.unified_msg_origin != self.unified_group_umo:
            yield event.plain_result("❌ 请在已绑定的MC互通群里使用本命令")
            return
        
        # 取命令后的完整文本；message_str 是原始文本，可能带唤醒前缀，用 find 定位命令本体
        raw = event.message_str.strip()
        idx = raw.find("mc喊话")
        message = raw[idx + len("mc喊话"):].strip() if idx >= 0 else ""
        
        if not message:
            yield event.plain_result("用法: mc喊话 <要说的话>")
            return
        
        sender_id = event.get_sender_id()
        now = time.monotonic()
        last = self._shout_cooldown.get(sender_id, 0)
        if now - last < 5:
            yield event.plain_result("说话太快了，请 5 秒后再试")
            return
        
        sender_name = event.get_sender_name() or sender_id
        prefix = f"[群聊] {sender_name}: "
        for command in build_tellraw_commands(message, prefix=prefix, color="yellow"):
            result = await self.rcon.execute_async(command)
            if result.startswith("错误:"):
                yield event.plain_result(f"❌ 发送到MC失败：{result}")
                return
        
        self._shout_cooldown[sender_id] = now
        yield event.plain_result("✓ 已发送到MC")
    
    @filter.command("mc_kb_rebuild")
    async def cmd_kb_rebuild(self, event: AstrMessageEvent):
        """重建物品知识库（扫描服务端 mods/ 与 kubejs/，合并原版与 CFPA 汉化）"""
        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            yield event.plain_result(error_msg)
            return
        
        if self.kb is None:
            yield event.plain_result("物品知识库不可用：插件数据目录初始化失败，请查看 AstrBot 日志")
            return
        
        if not self.kb.enabled:
            yield event.plain_result("未配置 mc_server_dir（MC 服务器根目录），无法扫描 mods/。请先在插件配置里填写后重试")
            return
        
        yield event.plain_result("⏳ 正在重建物品知识库（扫描 mods/ 通常需要几秒到几十秒，请稍候）...")
        
        def _log(message):
            logger.info(f"[MC知识库] {message}")
        
        result = await asyncio.to_thread(self.kb.rebuild, _log)
        yield event.plain_result(result)
    
    @filter.command("mc_kb_dump")
    async def cmd_kb_dump(self, event: AstrMessageEvent):
        """一键导出运行时注册表并重建物品知识库（自动部署 KubeJS 脚本，无需手工处理日志）"""
        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            yield event.plain_result(error_msg)
            return
        
        if self.kb is None:
            yield event.plain_result("物品知识库不可用：插件数据目录初始化失败，请查看 AstrBot 日志")
            return
        
        if not self.kb.enabled:
            yield event.plain_result("未配置 mc_server_dir（MC 服务器根目录），无法导出运行时 dump。请先在插件配置里填写后重试")
            return
        
        if self._dump_lock.locked():
            yield event.plain_result("⏳ 已有 dump 流程在进行中，请等它结束（结果会单独回执）")
            return
        
        # 锁在第一次 yield 之前拿到：locked() 检查与 async with 之间没有 await，不会并发放行
        async with self._dump_lock:
            yield event.plain_result("⏳ 正在导出运行时注册表（首次会自动部署脚本并 /reload，可能需要几十秒）...")
            
            def _log(message):
                logger.info(f"[MC运行时dump] {message}")
            
            try:
                runner = RuntimeDumpRunner(self.mc_server_dir, self.rcon)
                result = await runner.run(lambda: self.kb.rebuild(_log))
            except Exception as exc:  # 编排异常不能拖垮插件，堆栈进日志
                logger.exception("运行时 dump 流程异常")
                result = f"❌ 运行时 dump 异常：{exc}"
            
            yield event.plain_result(result)
    
    @filter.command("mc_kb_status")
    async def cmd_kb_status(self, event: AstrMessageEvent):
        """查看物品知识库构建状态与覆盖率"""
        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            yield event.plain_result(error_msg)
            return
        
        if self.kb is None:
            yield event.plain_result("物品知识库不可用：插件数据目录初始化失败，请查看 AstrBot 日志")
            return
        
        yield event.plain_result(self.kb.status())
