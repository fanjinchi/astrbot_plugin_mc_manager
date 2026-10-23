"""
游戏操作工具
包含给予物品、传送、游戏模式功能
"""

from typing import TYPE_CHECKING

from .id_utils import normalize_mc_id

if TYPE_CHECKING:
    from ..rcon_client import MinecraftRCON


# 全局RCON客户端引用，由main.py注入
_rcon: "MinecraftRCON" = None


def set_rcon(rcon: "MinecraftRCON"):
    """设置RCON客户端"""
    global _rcon
    _rcon = rcon


def get_rcon() -> "MinecraftRCON":
    """获取RCON客户端"""
    if _rcon is None:
        raise RuntimeError("RCON客户端未初始化")
    return _rcon


# ============ 工具函数定义 ============


async def give_item(player: str, item: str, count: int = 1) -> str:
    """
    给予玩家物品

    Args:
        player(string): 要给予物品的玩家名称，使用@p表示最近的玩家，@a表示所有玩家
        item(string): 物品ID，例如diamond、iron_sword、minecraft:golden_apple；模组物品用完整ID，如 create:brass_ingot
        count(number): 物品数量，默认为1，最大64

    Returns:
        执行结果信息
    """
    rcon = get_rcon()
    # 补全原版 ID 的命名空间，模组 ID 原样保留
    item = normalize_mc_id(item)
    
    # 限制数量范围
    count = max(1, min(count, 64))
    
    result = await rcon.execute_async(f"give {player} {item} {count}")
    return f"给予 {player} {count}个 {item}: {result}"


async def teleport_player(player: str, target: str) -> str:
    """
    传送玩家到目标位置或其他玩家

    Args:
        player(string): 要传送的玩家名称
        target(string): 目标位置（x y z坐标，如"100 64 200"）或目标玩家名称

    Returns:
        执行结果信息
    """
    rcon = get_rcon()
    result = await rcon.execute_async(f"tp {player} {target}")
    return f"传送 {player} 到 {target}: {result}"


async def set_gamemode(player: str, mode: str) -> str:
    """
    设置玩家的游戏模式

    Args:
        player(string): 要设置游戏模式的玩家名称
        mode(string): 游戏模式，可选值：survival（生存）、creative（创造）、adventure（冒险）、spectator（旁观）

    Returns:
        执行结果信息
    """
    rcon = get_rcon()
    
    # 标准化游戏模式名称
    mode_map = {
        "生存": "survival",
        "创造": "creative", 
        "冒险": "adventure",
        "旁观": "spectator",
        "0": "survival",
        "1": "creative",
        "2": "adventure",
        "3": "spectator",
    }
    mode = mode_map.get(mode.lower(), mode.lower())
    
    result = await rcon.execute_async(f"gamemode {mode} {player}")
    return f"设置 {player} 的游戏模式为 {mode}: {result}"
