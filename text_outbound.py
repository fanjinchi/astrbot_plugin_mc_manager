"""
RCON 出站文本工具（纯函数，无 AstrBot 依赖，可独立测试）

为什么存在：原版 RCON 服务端的读取缓冲是 byte[1460]，单个命令包超限会被
**静默拔线**——命令不送达、无任何回执（兄弟插件 Scintilla 实测结论，
其 core/text_outbound.py 有完整考证）。中文经 tellraw 下发时 1 个汉字
占 3 字节，几百字的长文本很容易踩线，所以这里统一做字节预算切段。

预算推导：命令预算 1400B（1460 留 60B 协议余量）。
切段在**转义前的原文**上进行：JSON 转义最坏情况是逐字符翻倍
（" 变 \\"，换行变 \\n），所以原文预算取 (1400 - 包装开销) / 2，
可保证转义后必然不超 1400B。
"""

# 单个 RCON 命令包的 UTF-8 字节预算（服务端硬限制 1460，预留协议余量）
MAX_RCON_COMMAND_BYTES = 1400

# tellraw @a {"text":"","color":"aqua"} 的固定包装开销（实测约 40B）
_TELLRAW_WRAPPER_BYTES = len('tellraw @a {"text":"","color":"aqua"}'.encode("utf-8"))


def escape_json_text(text: str) -> str:
    """tellraw JSON 文本转义（与项目既有写法一致：先反斜杠再引号再换行）"""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def build_tellraw_command(text: str, color: str = "aqua", target: str = "@a") -> str:
    """拼一条 tellraw 命令。text 必须先经过 chunk_text_for_rcon 切段控制长度"""
    return f'tellraw {target} {{"text":"{escape_json_text(text)}","color":"{color}"}}'


def chunk_text_for_rcon(text: str, prefix: str = "") -> list[str]:
    """
    把消息切成若干段，保证每段拼成 tellraw 命令后（含 prefix）不超字节预算。

    Args:
        text: 消息原文（切段在转义前进行，按最坏 2 倍膨胀留余量）
        prefix: 每段都要带的前缀（如 "[Bot] "），其字节数计入预算

    Returns:
        段列表；每段都是完整字符（不会劈开多字节字符），优先在换行处断开
    """
    wrapper = _TELLRAW_WRAPPER_BYTES + len(prefix.encode("utf-8"))
    raw_budget = (MAX_RCON_COMMAND_BYTES - wrapper) // 2
    raw_budget = max(raw_budget, 32)  # 极端长前缀也保证能发出东西

    chunks: list[str] = []
    current = ""
    current_bytes = 0
    for ch in text:
        ch_bytes = len(ch.encode("utf-8"))
        if current_bytes + ch_bytes > raw_budget:
            chunks.append(current)
            current = ""
            current_bytes = 0
        current += ch
        current_bytes += ch_bytes
        if ch == "\n":
            chunks.append(current)
            current = ""
            current_bytes = 0
    if current or not chunks:
        chunks.append(current)
    return chunks


def build_tellraw_commands(text: str, prefix: str = "", color: str = "aqua", target: str = "@a") -> list[str]:
    """一条龙：切段 + 转义 + 拼命令，返回若干条不超字节预算的 tellraw 命令"""
    return [build_tellraw_command(prefix + chunk, color=color, target=target) for chunk in chunk_text_for_rcon(text, prefix)]
