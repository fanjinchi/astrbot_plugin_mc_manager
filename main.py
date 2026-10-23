"""
AstrBot MC服务器管理插件
通过LLM智能管理Minecraft服务器，支持Fabric/Forge/NeoForge
"""

import asyncio
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api import AstrBotConfig, logger
from astrbot.core.provider.entities import LLMResponse

from .rcon_client import MinecraftRCON
from .tools import game_tools, server_tools, world_tools
from .log_client import LogClient
from .kb import KnowledgeBase
from .kb import commands as cmd_kb


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
        
        # 唤醒词配置已移除 - 所有消息都提交，由AstrBot框架层唤醒词决定是否调用LLM
        # 旧配置: self.wake_words = self.config.get("wake_words", ["bot"])
        
        # 是否启用聊天响应
        self.enable_chat_response = self.config.get("enable_chat_response", True)
        
        # 加载机器人昵称配置
        self.bot_nickname = self.config.get("bot_nickname", "Bot")
        
        # 加载统一上下文配置
        self.enable_unified_context = self.config.get("enable_unified_context", False)
        self.unified_group_umo = self.config.get("unified_group_umo", "")
        self.mc_message_prefix = self.config.get("mc_message_prefix", "[MC]")
        
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
        
        # 初始化日志客户端（如果启用）
        self.log_client = None
        enable_log = self.config.get("enable_log_monitor", False)
        if enable_log:
            log_host = self.config.get("log_server_host", "127.0.0.1")
            log_port = self.config.get("log_server_port", 25576)
            reconnect_interval = self.config.get("log_reconnect_interval", 10)
            max_reconnect_attempts = self.config.get("log_max_reconnect_attempts", 0)
            
            # 所有MC消息都会提交到AstrBot，由框架的wake_prefix控制是否调用LLM
            self.log_client = LogClient(
                log_host,
                log_port,
                reconnect_interval=reconnect_interval,
                max_reconnect_attempts=max_reconnect_attempts
            )
            self.log_client.set_chat_callback(self._on_player_chat)
            self.log_client.set_fake_event_handler(self._send_fake_event)
            self.log_client.set_disconnect_callback(self._on_log_disconnect)
            self.log_client.set_reconnect_callback(self._on_log_reconnect)
            self.log_client.set_player_join_callback(self._on_player_join)
            self.log_client.set_player_leave_callback(self._on_player_leave)
            self.log_client.set_player_advancement_callback(self._on_player_advancement)
            self.log_client.set_player_death_callback(self._on_player_death)
        
        # 注入RCON客户端到所有工具模块
        self._inject_rcon()
        
        logger.info(f"MC Manager插件已加载，RCON: {self.config.get('rcon_host')}:{self.config.get('rcon_port')}")
    
    async def initialize(self):
        """插件激活时自动调用 - 启动长连接任务"""
        # 启动日志客户端（包含自动重连功能）
        if self.log_client:
            asyncio.create_task(self.log_client.start_listening())
            logger.info("日志监控已启动（支持自动重连）")
    
    def _inject_rcon(self):
        """将RCON客户端注入到所有工具模块"""
        game_tools.set_rcon(self.rcon)
        server_tools.set_rcon(self.rcon)
        server_tools.set_dangerous_commands_enabled(self.enable_dangerous)
        world_tools.set_rcon(self.rcon)
    
    async def _on_player_chat(self, player: str, message: str, time: str):
        """
        处理玩家聊天消息的回调函数
        
        Args:
            player: 玩家名称
            message: 聊天消息内容
            time: 消息时间
        """
        pass
    
    async def _on_log_disconnect(self):
        """日志服务器断连回调"""
        logger.warning("与日志服务器的连接已断开")
    
    async def _on_log_reconnect(self):
        """日志服务器重连成功回调"""
        logger.info("已重新连接到日志服务器")
    
    async def _on_player_join(self, player: str):
        """
        玩家登入事件回调
        
        Args:
            player: 玩家名称
        """
        logger.info(f"[MC事件] 玩家 {player} 加入了游戏")
        
        # 伪造事件提交到AstrBot，让LLM感知到登入事件
        event_message = f"[系统消息] {player} 加入了游戏"
        await self._send_system_event(player, event_message)
    
    async def _on_player_leave(self, player: str):
        """
        玩家登出事件回调
        
        Args:
            player: 玩家名称
        """
        logger.info(f"[MC事件] 玩家 {player} 离开了游戏")
        
        # 伪造事件提交到AstrBot
        event_message = f"[系统消息] {player} 离开了游戏"
        await self._send_system_event(player, event_message)
    
    async def _on_player_advancement(self, player: str, advancement: str):
        """
        玩家达成成就事件回调
        
        Args:
            player: 玩家名称
            advancement: 成就名称
        """
        logger.info(f"[MC事件] 玩家 {player} 达成了成就 [{advancement}]")
        
        # 伪造事件提交到AstrBot
        event_message = f"[系统消息] {player} 达成了成就 [{advancement}]"
        await self._send_system_event(player, event_message)
    
    async def _on_player_death(self, player: str, reason: str):
        """
        玩家死亡事件回调
        
        Args:
            player: 玩家名称
            reason: 死因描述
        """
        logger.info(f"[MC事件] 玩家死亡: {reason}")
        
        # 伪造事件提交到AstrBot
        event_message = f"[系统消息] {reason}"
        await self._send_system_event(player, event_message)
    
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
                self_id="astrbot_mc_plugin",
                session_id=mc_session_id,
                sender=sender,
                message=[Plain(message_text)],
                message_str=message_text,
                group_id=group_id
            )
            
            # 提交事件到AstrBot
            # - is_wake=False 让框架根据唤醒词配置决定是否调用LLM
            # - LTM仍然会记录所有消息作为上下文
            await StarTools.create_event(
                abm=new_message,
                platform="aiocqhttp",
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
                self_id="astrbot_mc_plugin",
                session_id=mc_session_id,
                sender=sender,
                message=[Plain(event_message)],
                message_str=event_message,
                group_id=group_id
            )
            
            # 提交事件到AstrBot（不触发唤醒，但会记录到LTM）
            await StarTools.create_event(
                abm=new_message,
                platform="aiocqhttp",
                is_wake=False
            )
            
            logger.info(f"MC系统事件已提交: {event_message}")
            
        except Exception as e:
            logger.error(f"提交MC系统事件失败: {e}")
    
    
    async def terminate(self):
        """插件禁用/重载时自动调用 - 清理资源"""
        # 物品知识库按"连接即用即关"实现（store.py），没有需要关闭的长连接
        # 断开日志客户端（停止自动重连）
        if self.log_client:
            await self.log_client.disconnect(stop_reconnect=True)
            logger.info("日志监控已停止")
    
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
        将消息发送到MC服务器聊天框
        
        Args:
            message: 要发送的消息内容
        """
        try:
            # MC聊天框有长度限制，需要分段发送
            max_length = 200  # 每段最大长度
            
            # 处理换行符，分段发送
            lines = message.split('\n')
            current_chunk = ""
            
            for line in lines:
                # 如果当前行太长，需要进一步拆分
                if len(line) > max_length:
                    # 先发送当前累积的内容
                    if current_chunk:
                        await self._send_single_mc_message(current_chunk)
                        current_chunk = ""
                    
                    # 拆分长行
                    for i in range(0, len(line), max_length):
                        chunk = line[i:i + max_length]
                        await self._send_single_mc_message(chunk)
                else:
                    # 检查添加这行后是否超长
                    test_chunk = current_chunk + ('\n' if current_chunk else '') + line
                    if len(test_chunk) > max_length:
                        # 先发送当前累积的内容
                        if current_chunk:
                            await self._send_single_mc_message(current_chunk)
                        current_chunk = line
                    else:
                        current_chunk = test_chunk
            
            # 发送剩余内容
            if current_chunk:
                await self._send_single_mc_message(current_chunk)
                
        except Exception as e:
            logger.error(f"发送消息到MC聊天框失败: {e}")
    
    async def _send_single_mc_message(self, message: str):
        """
        发送单条消息到MC聊天框
        
        Args:
            message: 消息内容
        """
        try:
            # 转义JSON特殊字符
            escaped_message = message.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            
            # 使用tellraw命令发送消息给所有玩家
            json_text = f'{{"text":"[{self.bot_nickname}] {escaped_message}", "color":"aqua"}}'
            command = f'tellraw @a {json_text}'
            
            result = await self.rcon.execute_async(command)
        except Exception as e:
            logger.error(f"发送单条消息到MC失败: {e}")
    
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
        
        在内置的原版命令知识库（以及服务器导出的模组命令，如有）里按命令名或中文描述模糊搜索，
        返回命令语法、说明和游戏内权限等级。准备调用 execute_command 但不确定命令怎么写时先用它查。
        
        Args:
            keyword(string): 搜索关键词，如「封禁」「ban」「weather」「传送」
            limit(number): 最多返回条数，默认8
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
        
        # 检查是否启用了统一上下文
        if not self.enable_unified_context:
            return "❌ 未启用统一上下文功能(enable_unified_context)，无法发送到QQ群"
        
        # 检查是否配置了UMO
        if not self.unified_group_umo:
            return "❌ 未配置统一上下文UMO(unified_group_umo)，无法发送到QQ群"
        
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
        """测试与日志服务器的连接并读取最新一条日志"""
        has_permission, error_msg = self._check_permission(event)
        if not has_permission:
            yield event.plain_result(error_msg)
            return
        
        if not self.log_client:
            yield event.plain_result("日志监控功能未启用")
            return
        
        try:
            success, log_content = await self.log_client.test_connection()
            yield event.plain_result(log_content)
        except Exception as e:
            yield event.plain_result(f"错误: {e}")
    
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
