"""
世界操作工具
包含天气、时间、生成实体功能
"""

from typing import TYPE_CHECKING, Optional

from .id_utils import normalize_mc_id

if TYPE_CHECKING:
    from ..rcon_client import MinecraftRCON


# 全局RCON客户端引用
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


async def set_weather(weather_type: str, duration: Optional[int] = None) -> str:
    """
    设置游戏天气

    Args:
        weather_type(string): 天气类型，可选值：clear（晴天）、rain（雨天）、thunder（雷暴）
        duration(number): 可选，持续时间（秒），不填则使用默认时间

    Returns:
        执行结果信息
    """
    rcon = get_rcon()
    
    # 标准化天气类型
    weather_map = {
        "晴天": "clear",
        "晴": "clear",
        "雨天": "rain",
        "下雨": "rain",
        "雨": "rain",
        "雷暴": "thunder",
        "雷雨": "thunder",
        "打雷": "thunder",
    }
    weather_type = weather_map.get(weather_type, weather_type.lower())
    
    if weather_type not in ["clear", "rain", "thunder"]:
        return f"错误: 无效的天气类型 '{weather_type}'，可选值：clear、rain、thunder"
    
    if duration:
        result = await rcon.execute_async(f"weather {weather_type} {duration}")
    else:
        result = await rcon.execute_async(f"weather {weather_type}")
    
    return f"设置天气为 {weather_type}: {result}"


async def set_time(time_value: str) -> str:
    """
    设置游戏时间

    Args:
        time_value(string): 时间值，可以是数字（游戏刻）或预设值：day（白天）、noon（正午）、night（夜晚）、midnight（午夜）

    Returns:
        执行结果信息
    """
    rcon = get_rcon()
    
    # 标准化时间值
    time_map = {
        "白天": "day",
        "日出": "day",
        "正午": "noon",
        "中午": "noon",
        "夜晚": "night",
        "晚上": "night",
        "午夜": "midnight",
        "凌晨": "midnight",
        "日落": "18000",
    }
    time_value = time_map.get(time_value, time_value.lower())
    
    result = await rcon.execute_async(f"time set {time_value}")
    return f"设置时间为 {time_value}: {result}"


async def summon_entity(entity: str, x: Optional[float] = None, y: Optional[float] = None, z: Optional[float] = None) -> str:
    """
    在指定位置生成实体

    Args:
        entity(string): 实体类型，如zombie、creeper、pig、minecraft:iron_golem等；模组实体用完整ID，如 iceandfire:fire_dragon
        x(number): 可选，X坐标，不填则在随机位置生成
        y(number): 可选，Y坐标
        z(number): 可选，Z坐标

    Returns:
        执行结果信息
    """
    rcon = get_rcon()
    
    # 补全原版 ID 的命名空间，模组 ID 原样保留
    entity = normalize_mc_id(entity)
    
    if x is not None and y is not None and z is not None:
        result = await rcon.execute_async(f"summon {entity} {x} {y} {z}")
        return f"在 ({x}, {y}, {z}) 生成 {entity}: {result}"
    else:
        result = await rcon.execute_async(f"summon {entity}")
        return f"生成 {entity}: {result}"
