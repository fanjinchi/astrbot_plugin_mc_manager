"""
Minecraft 资源 ID 工具
"""


def normalize_mc_id(raw: str) -> str:
    """标准化资源 ID：未带命名空间时补 minecraft: 前缀

    原版 ID 可省略命名空间（stone -> minecraft:stone）；
    模组 ID 必须带命名空间（create:brass_ingot），原样保留。

    Args:
        raw: 玩家或 LLM 传入的资源 ID

    Returns:
        带命名空间的资源 ID
    """
    raw = raw.strip()
    if ":" in raw:
        return raw
    return f"minecraft:{raw}"
