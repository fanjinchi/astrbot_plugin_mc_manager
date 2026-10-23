"""MC 命令知识库查询（原版内置 + 模组导出合并）。

原版命令是随插件分发的固定数据（assets/vanilla_commands.json），无需配置、无需重建；
模组命令来自数据目录下的 runtime_dump/commands.jsonl（issue #5 的运行时导出，可选增强）。
"""

import json
import os
from typing import Optional

try:
    from astrbot.api import logger
except ImportError:  # 允许脱离 AstrBot 环境独立测试
    import logging

    logger = logging.getLogger("mc_manager.kb.commands")

_VANILLA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "vanilla_commands.json",
)

_CAT_LABEL = {
    "info": "信息查询",
    "player": "玩家管理",
    "server": "服务器",
    "game": "游戏操作",
    "world": "世界",
}

_vanilla_cache = None


def _load_vanilla() -> list:
    """加载原版命令清单（模块级缓存，进程内只读一次）。"""
    global _vanilla_cache
    if _vanilla_cache is None:
        try:
            with open(_VANILLA_PATH, encoding="utf-8") as f:
                rows = json.load(f)
            for row in rows:
                row.setdefault("source", "vanilla")
            _vanilla_cache = rows
        except Exception as exc:
            logger.warning("原版命令知识库加载失败: %s", exc)
            _vanilla_cache = []
    return _vanilla_cache


def _load_mod_commands(data_dir: Optional[str] = None) -> list:
    """读取模组命令导出（runtime_dump/commands.jsonl），不存在则返回空列表。"""
    if not data_dir:
        return []
    path = os.path.join(data_dir, "runtime_dump", "commands.jsonl")
    if not os.path.isfile(path):
        return []
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("name"):
                    rows.append(row)
    except Exception as exc:
        logger.warning("模组命令导出读取失败 %s: %s", path, exc)
        return []
    return rows


def search_commands(keyword: str, limit: int = 8, data_dir: Optional[str] = None) -> str:
    """按命令名/中文描述模糊搜索，返回给 LLM 的文案。"""
    kw = (keyword or "").strip().lower()
    if not kw:
        return "请提供搜索关键词（命令名或中文描述，如「封禁」「weather」）。"
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 8

    entries = list(_load_vanilla())
    entries.extend(_load_mod_commands(data_dir))

    scored = []
    for e in entries:
        name = (e.get("name") or "").lower()
        desc = (e.get("desc") or "").lower()
        syntax = (e.get("syntax") or "").lower()
        if name == kw:
            score = 0
        elif name.startswith(kw):
            score = 1
        elif kw in name:
            score = 2
        elif kw in desc or kw in syntax:
            score = 3
        else:
            continue
        scored.append((score, name, e))
    scored.sort(key=lambda t: (t[0], t[1]))
    top = scored[:limit]

    if not top:
        return ("未找到与「%s」相关的命令。原版命令以本知识库为准；模组命令需服务器侧 "
                "runtime dump 导出后才会被收录。" % keyword)

    lines = ["找到 %d 个匹配「%s」的命令：" % (len(top), keyword)]
    for _, _, e in top:
        lines.append(_format_entry(e))
    if len(scored) > limit:
        lines.append("（只显示前 %d 条，可用更精确的关键词）" % limit)
    return "\n".join(lines)


def _format_entry(e: dict) -> str:
    src = e.get("source", "vanilla")
    src_label = "原版" if src == "vanilla" else src
    level = e.get("level")
    level_label = "，游戏内需 %d 级权限" % level if isinstance(level, int) else ""
    cat = _CAT_LABEL.get(e.get("cat"), e.get("cat") or "")
    return "- /%s — %s\n  语法：%s（%s%s%s）" % (
        e.get("name"), e.get("desc"), e.get("syntax"), src_label,
        "，" + cat if cat else "", level_label)
