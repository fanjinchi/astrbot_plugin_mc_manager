"""
服务器管理工具
包含查看玩家、格式化消息、自定义命令执行功能
"""

import shlex
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


async def tellraw(
    message: str, sender: str = "Bot", color: str = "yellow", target: str = "@a"
) -> str:
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

    result = await rcon.execute_async(f"tellraw {target} {json_text}")
    return f"发送消息到 {target}: <{sender}> {message} [{result}]"


def _execute_run_offset(tokens: list[str]) -> int:
    """Return the token offset after the outer execute command's run literal.

    Args:
        tokens: Tokenized command beginning with execute.

    Returns:
        The offset of the first token in the command executed by run.

    Raises:
        ValueError: If the execute chain is unsupported or incomplete.
        IndexError: If a known clause is missing arguments.
    """
    index = 1
    while index < len(tokens):
        clause = tokens[index].lower()
        if clause == "run":
            return index + 1
        if clause in {"align", "anchored", "as", "at", "in"}:
            index += 2
        elif clause == "positioned":
            index += 3 if tokens[index + 1].lower() == "as" else 4
        elif clause in {"facing", "rotated"}:
            # Both forms have three argument tokens: vec3, entity+anchor, or rot/as+target.
            index += 4 if clause == "facing" else 3
        elif clause in {"if", "unless"}:
            condition = tokens[index + 1].lower()
            if condition in {"biome", "block"}:
                index += 6
            elif condition == "blocks":
                index += 12
            elif condition == "data":
                source = tokens[index + 2].lower()
                if source == "block":
                    index += 7
                elif source in {"entity", "storage"}:
                    index += 5
                else:
                    raise ValueError("Unknown execute data source")
            elif condition in {"dimension", "entity", "function", "predicate"}:
                index += 3
            elif condition == "loaded":
                index += 5
            elif condition == "score":
                comparison = tokens[index + 4].lower()
                if comparison == "matches":
                    index += 6
                elif comparison in {"<", "<=", "=", ">=", ">"}:
                    index += 7
                else:
                    raise ValueError("Unknown execute score comparison")
            else:
                raise ValueError("Unknown execute condition")
        elif clause == "store":
            if tokens[index + 1].lower() not in {"result", "success"}:
                raise ValueError("Unknown execute store mode")
            target = tokens[index + 2].lower()
            if target == "block":
                index += 9
            elif target in {"entity", "storage"}:
                index += 7
            elif target in {"bossbar", "score"}:
                index += 5
            else:
                raise ValueError("Unknown execute store target")
        else:
            raise ValueError("Unknown execute clause")
    raise ValueError("Execute command has no run clause")


def _find_dangerous_command(command: str) -> str | None:
    """Find a dangerous command at the root or behind nested execute run clauses.

    Args:
        command: Raw Minecraft command.

    Returns:
        The normalized dangerous command name, or None for an allowed command.

    Raises:
        ValueError: If tokenization fails or an execute chain cannot be parsed safely.
        IndexError: If an execute clause is incomplete.
    """
    tokens = shlex.split(command, comments=False, posix=True)
    dangerous_commands = {
        "stop",
        "op",
        "deop",
        "ban",
        "ban-ip",
        "pardon",
        "pardon-ip",
    }
    dangerous_whitelist_subcommands = {"on", "off", "add", "remove", "reload"}

    while tokens:
        root = tokens[0].lower().removeprefix("/")
        if root.startswith("minecraft:"):
            root = root.removeprefix("minecraft:")
        if root in dangerous_commands:
            return root
        if (
            root == "whitelist"
            and len(tokens) > 1
            and tokens[1].lower() in dangerous_whitelist_subcommands
        ):
            return root
        if root != "execute":
            return None
        tokens = tokens[_execute_run_offset(tokens) :]

    raise ValueError("Execute run clause has no command")


async def execute_command(command: str) -> str:
    """
    执行自定义Minecraft命令（高级功能）

    Args:
        command(string): 要执行的Minecraft命令（不需要/前缀）

    Returns:
        命令执行结果
    """
    if not command.strip():
        return "错误: 命令不能为空。"

    if not _enable_dangerous_commands:
        try:
            dangerous_command = _find_dangerous_command(command)
        except (ValueError, IndexError):
            return "错误: 无法可靠解析命令，已停止执行。"
        if dangerous_command:
            return f"错误: 命令 '{dangerous_command}' 是危险命令，已被禁用。"

    rcon = get_rcon()
    result = await rcon.execute_async(command)
    return f"执行命令 '{command}': {result}"
