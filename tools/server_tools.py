"""
服务器管理工具
包含查看玩家、格式化消息、自定义命令执行功能
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..rcon_client import MinecraftRCON


# 全局RCON客户端引用和配置
_rcon: "MinecraftRCON" = None
_enable_dangerous_commands: bool = False


def set_rcon(rcon: "MinecraftRCON"):
    """设置RCON客户端"""
    global _rcon
    _rcon = rcon


def set_dangerous_commands_enabled(enabled: bool):
    """设置是否允许危险命令"""
    global _enable_dangerous_commands
    _enable_dangerous_commands = enabled


def get_rcon() -> "MinecraftRCON":
    """获取RCON客户端"""
    if _rcon is None:
        raise RuntimeError("RCON客户端未初始化")
    return _rcon


# ============ 工具函数定义 ============


async def list_players() -> str:
    """
    获取当前在线玩家列表

    Returns:
        在线玩家信息
    """
    rcon = get_rcon()
    result = await rcon.execute_async("list")
    return f"在线玩家: {result}"


async def tellraw(message: str, sender: str = "Bot", color: str = "yellow", target: str = "@a") -> str:
    """
    通过tellraw在游戏公屏发送聊天消息

    Args:
        message(string): 要发送的消息内容
        sender(string): 发送者名称，默认为"Bot"
        color(string): 消息颜色，可选值：yellow/red/green/blue/white/gold/aqua/dark_red等，默认为yellow
        target(string): 目标玩家，默认@a（所有玩家）

    Returns:
        执行结果信息
    """
    rcon = get_rcon()
    
    # 转义消息中的特殊字符
    message = message.replace('"', '\\"')
    sender = sender.replace('"', '\\"')
    
    # 构建JSON格式的tellraw命令
    json_text = f'{{"text":"<{sender}> {message}", "color":"{color}"}}'
    
    result = await rcon.execute_async(f'tellraw {target} {json_text}')
    return f"发送消息到 {target}: <{sender}> {message} [{result}]"


async def execute_command(command: str) -> str:
    """
    执行自定义Minecraft命令（高级功能）

    Args:
        command(string): 要执行的Minecraft命令（不需要/前缀）

    Returns:
        命令执行结果
    """
    rcon = get_rcon()
    
    # 检查危险命令
    dangerous_commands = ["stop", "ban-ip"]
    cmd_base = command.split()[0].lower() if command else ""
    
    if cmd_base in dangerous_commands and not _enable_dangerous_commands:
        return f"错误: 命令 '{cmd_base}' 是危险命令，已被禁用。"
    
    result = await rcon.execute_async(command)
    return f"执行命令 '{command}': {result}"
