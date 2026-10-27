"""MC 命令知识库查询（原版内置 + 运行时导出合并）。

原版命令是随插件分发的固定数据（assets/vanilla_commands.json），无需配置、无需重建；
运行时命令来自数据目录下 runtime_dump/commands.json —— 这是 KubeJS 主路径与 RCON help
回退路径共用的快照契约（producer 区分语法可信度）。查询永远只读已发布的派生快照，
不在 execute_command 前实时扫描服务器。
"""

import json
import os
import re
import tempfile
from typing import Optional

try:
    from astrbot.api import logger
except ImportError:  # 允许脱离 AstrBot 环境独立测试
    import logging

    logger = logging.getLogger("mc_manager.kb.commands")

_VANILLA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "vanilla_commands.json",
)

_CAT_LABEL = {
    "info": "信息查询",
    "player": "玩家管理",
    "server": "服务器",
    "game": "游戏操作",
    "world": "世界",
}

# 共享快照契约（见 .trellis/tasks/10-25-mod-command-kb/design.md §2）：
# 扁平 usage 条目，kind/schema_version/producer/count/entries 五字段冻结。
SNAPSHOT_KIND = "commands"
SNAPSHOT_VERSION = 1
SNAPSHOT_PRODUCERS = ("kubejs", "rcon")
SNAPSHOT_DIR = "runtime_dump"
SNAPSHOT_NAME = "commands.json"
LEGACY_NAME = "commands.jsonl"
# 单根最多展示的 usage 行数：/execute 这类根有上百条路径，全列会淹没上下文
USAGE_PER_ROOT = 8

# 查询归一化：空白、下划线、连字符在比较时视为等价分隔（channel mode / channel_mode /
# channel-mode / channelmode 命中同一 usage）。`->` 是 redirect 结构标记，先用哨兵保护，
# 避免被当成普通连字符拆成空 token 和 ">"。
_ARROW_SENTINEL = "\x00"
_TOKEN_SPLIT = re.compile(r"[\s_\-]+")
_SQUASH = re.compile(r"[\s_]+|-(?!>)")

_EMPTY_QUERY_HINT = (
    "请提供搜索关键词（命令名、中文描述或英文概念词，如「封禁」「weather」「waystone」）。"
    "模组命令只有英文名与参数语法，中文意图请先提炼成简短英文词。"
)

_vanilla_cache = None


def _load_vanilla() -> list:
    """加载原版命令清单（模块级缓存，进程内只读一次；固定数据才允许缓存）。"""
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


# ------------------------------------------------------------------ 快照校验与发布


def snapshot_path(data_dir: str) -> str:
    return os.path.join(data_dir, SNAPSHOT_DIR, SNAPSHOT_NAME)


def _legacy_path(data_dir: str) -> str:
    return os.path.join(data_dir, SNAPSHOT_DIR, LEGACY_NAME)


def normalize_entries(entries: list) -> list:
    """按 name + syntax + redirect 去重并稳定排序（发布与查询共用同一口径）。"""
    unique = {}
    for entry in entries:
        key = (entry["name"], entry["syntax"], entry.get("redirect", ""))
        unique.setdefault(key, entry)
    return [unique[key] for key in sorted(unique)]


def validate_snapshot(data) -> tuple:
    """校验整份命令快照，返回 (规范化快照, 错误原因)；错误原因非空即拒绝发布/读取。"""
    if not isinstance(data, dict):
        return None, "顶层不是 JSON 对象"
    if data.get("kind") != SNAPSHOT_KIND:
        return None, "kind 不是 %s" % SNAPSHOT_KIND
    if data.get("schema_version") != SNAPSHOT_VERSION:
        return None, "schema_version 不是 %d" % SNAPSHOT_VERSION
    producer = data.get("producer")
    if producer not in SNAPSHOT_PRODUCERS:
        return None, "producer 不是 %s 之一" % " / ".join(SNAPSHOT_PRODUCERS)
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        return None, "entries 缺失或为空"
    count = data.get("count")
    if not isinstance(count, int) or count != len(raw_entries):
        return None, "count 与实际条目数不一致"

    entries = []
    for index, entry in enumerate(raw_entries, 1):
        if not isinstance(entry, dict):
            return None, "第 %d 条不是对象" % index
        name = entry.get("name")
        syntax = entry.get("syntax")
        if not isinstance(name, str) or not name.strip():
            return None, "第 %d 条缺 name" % index
        if not isinstance(syntax, str) or not syntax.strip():
            return None, "第 %d 条缺 syntax" % index
        name = name.strip()
        syntax = syntax.strip()
        if syntax.split(" ")[0] != name:
            return None, "第 %d 条 syntax 与 name 不一致" % index
        level = entry.get("level")
        row = {
            "name": name,
            "syntax": syntax,
            "source": entry.get("source")
            if isinstance(entry.get("source"), str)
            else "unknown",
            "level": level
            if isinstance(level, int) and not isinstance(level, bool)
            else None,
        }
        redirect = entry.get("redirect")
        if isinstance(redirect, str) and redirect.strip():
            row["redirect"] = redirect.strip()
        entries.append(row)

    entries = normalize_entries(entries)
    return {
        "kind": SNAPSHOT_KIND,
        "schema_version": SNAPSHOT_VERSION,
        "producer": producer,
        "count": len(entries),
        "entries": entries,
    }, ""


def publish_snapshot(snapshot: dict, data_dir: str) -> tuple:
    """原子发布已校验快照：同目录临时文件 + os.replace，失败不破坏旧快照。

    临时名用 mkstemp 保持唯一：/mc_kb_dump 有单飞锁但 /mc_kb_rebuild 没有，
    两者并发时固定 .tmp 名会互相截断。
    """
    target_dir = os.path.join(data_dir, SNAPSHOT_DIR)
    target = snapshot_path(data_dir)
    tmp = ""
    try:
        os.makedirs(target_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".commands-", suffix=".tmp", dir=target_dir)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        os.replace(tmp, target)
        return True, ""
    except OSError as exc:
        if tmp and os.path.isfile(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False, str(exc)


def import_snapshot(server_dir: str, data_dir: str) -> dict:
    """把服务器目录里的 KubeJS 命令快照导入并发布到插件数据目录。

    返回 {"status", "count", "roots", "producer", "warning"}；
    status ∈ missing（服务器上没有产物）/ published / invalid / error。
    """
    info = {"status": "missing", "count": 0, "roots": 0, "producer": "", "warning": ""}
    server_dir = (server_dir or "").strip()
    if not server_dir or not data_dir:
        return info
    raw_path = os.path.join(server_dir, SNAPSHOT_DIR, SNAPSHOT_NAME)
    if not os.path.isfile(raw_path):
        return info
    try:
        with open(raw_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        info["status"] = "invalid"
        info["warning"] = "命令快照读取失败（旧快照保持不变）：%s" % exc
        logger.warning("%s（%s）", info["warning"], raw_path)
        return info

    snapshot, reason = validate_snapshot(data)
    if snapshot is None:
        info["status"] = "invalid"
        info["warning"] = "命令快照校验失败（旧快照保持不变）：%s" % reason
        logger.warning("%s（%s）", info["warning"], raw_path)
        return info

    published, detail = publish_snapshot(snapshot, data_dir)
    if not published:
        info["status"] = "error"
        info["warning"] = "命令快照发布失败（旧快照保持不变）：%s" % detail
        logger.warning("%s（%s）", info["warning"], data_dir)
        return info
    info.update(
        status="published",
        count=snapshot["count"],
        roots=len({entry["name"] for entry in snapshot["entries"]}),
        producer=snapshot["producer"],
    )
    return info


def load_snapshot(data_dir: Optional[str]) -> tuple:
    """读取已发布快照，返回 (快照, 警告)。每次查询重读，不做进程级缓存。"""
    if not data_dir:
        return None, ""
    path = snapshot_path(data_dir)
    if not os.path.isfile(path):
        return None, ""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, "命令快照读取失败，已忽略：%s" % exc
    snapshot, reason = validate_snapshot(data)
    if snapshot is None:
        return None, "命令快照无效，已忽略：%s" % reason
    return snapshot, ""


def _load_legacy(data_dir: Optional[str]) -> list:
    """旧版 commands.jsonl：仅在 canonical 快照不存在时读取，坏行跳过。"""
    if not data_dir:
        return []
    path = _legacy_path(data_dir)
    if not os.path.isfile(path):
        return []
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("name") and row.get("syntax"):
                    rows.append(row)
    except OSError as exc:
        logger.warning("旧版模组命令文件读取失败 %s: %s", path, exc)
        return []
    return rows


# ------------------------------------------------------------------ 查询


def _group_roots(entries: list) -> dict:
    """把扁平 usage 条目按根命令聚合，redirect 单独成提示。"""
    roots = {}
    for entry in entries:
        name = (entry.get("name") or "").strip()
        syntax = (entry.get("syntax") or "").strip()
        if not name or not syntax:
            continue
        root = roots.get(name)
        if root is None:
            root = roots[name] = {"name": name, "usages": [], "redirects": []}
        redirect = entry.get("redirect")
        redirect = redirect.strip() if isinstance(redirect, str) else ""
        if redirect:
            hint = (
                "%s ..." % syntax
                if redirect == "..."
                else "%s -> %s" % (syntax, redirect)
            )
            if hint not in root["redirects"]:
                root["redirects"].append(hint)
        elif syntax not in root["usages"]:
            root["usages"].append(syntax)
    for root in roots.values():
        root["usages"].sort()
        root["redirects"].sort()
    return roots


def _merge_with_vanilla(root: dict, vanilla_row: Optional[dict]) -> dict:
    """运行时同根只继承内置 desc/cat；source 固定 unknown、level 未知。"""
    row = {
        "kind": "runtime",
        "name": root["name"],
        "usages": root["usages"],
        "redirects": root["redirects"],
        "desc": "",
        "cat": "",
        "source": "unknown",
        "level": None,
    }
    if vanilla_row:
        row["desc"] = vanilla_row.get("desc") or ""
        row["cat"] = vanilla_row.get("cat") or ""
    return row


def _squash(text: Optional[str]) -> str:
    """比较用归一化：小写并去掉空白、下划线、连字符（`->` 结构标记保留）。"""
    return _SQUASH.sub("", (text or "").lower())


def _split_query(query: str) -> list:
    """把查询拆成无序 token；连续分隔符不产生空 token，`->` 整体保留。"""
    protected = (query or "").lower().replace("->", _ARROW_SENTINEL)
    tokens = [token for token in _TOKEN_SPLIT.split(protected) if token]
    return [token.replace(_ARROW_SENTINEL, "->") for token in tokens]


def _rank(name: str, query_norm: str) -> int:
    """根名档位：精确 / 前缀 / 包含 / 仅内容命中；两种 producer 共用同一口径。"""
    if name == query_norm:
        return 0
    if name.startswith(query_norm):
        return 1
    if query_norm in name:
        return 2
    return 3


def _score_runtime(row: dict, tokens: list, query_norm: str) -> tuple:
    """运行时根打分：所有 token 必须在该根任一可搜索字段命中，顺序无关。

    精确/前缀/包含三档仍用整条归一化查询与根名比较（botania skyblock 与
    botania-skyblock 等价）；redirect 只参与根级 AND 与提示，不进入普通 usage。
    """
    name = _squash(row.get("name"))
    # 运行时同根继承了内置 desc，必须让它参与匹配：getAllUsage 覆盖整棵 dispatcher，
    # 快照里包含全部原版根，下列内置行随后会被跳过，若不在这里搜 desc，中文搜索会整体失效
    desc = _squash(row.get("desc"))
    usages = [(_squash(usage), usage) for usage in row.get("usages") or []]
    redirects = [_squash(hint) for hint in row.get("redirects") or []]
    fields = [name, desc] + [norm for norm, _usage in usages] + redirects

    for token in tokens:
        if token == "->":
            # 显式 -> 只认 redirect 结构，不能拿命令名/usage/desc 凑命中
            if not any("->" in hint for hint in redirects):
                return None, []
            continue
        if not any(token in field for field in fields):
            return None, []

    # 普通 usage 只有同一条语法覆盖全部 token 才进优先展示；
    # 否则「quest editing」会把同根里只提到 editing 的无关 usage 顶到最前
    matched = [
        usage for norm, usage in usages if all(token in norm for token in tokens)
    ]
    return _rank(name, query_norm), matched


def _score_vanilla(row: dict, tokens: list, query_norm: str) -> Optional[int]:
    name = _squash(row.get("name"))
    desc = _squash(row.get("desc"))
    syntax = _squash(row.get("syntax"))
    for token in tokens:
        if token == "->":
            return None  # 内置条目没有 redirect 结构，单独 -> 不匹配
        if not (token in name or token in desc or token in syntax):
            return None
    return _rank(name, query_norm)


def search_commands(
    keyword: str, limit: int = 8, data_dir: Optional[str] = None
) -> str:
    """按命令名/中文描述/参数语法搜索，返回给 LLM 的文案。

    关键词按空白、下划线、连字符拆成无序 token，每个 token 都要命中同一根（可以分别命中
    根名、描述、usage 或 redirect）；普通 usage 只有整条语法覆盖全部 token 才优先展示。
    显式 `->` 只匹配 redirect 结构，不拿命令名/usage 凑命中。
    """
    kw = (keyword or "").strip()
    tokens = _split_query(kw)
    if not tokens:
        return _EMPTY_QUERY_HINT
    query_norm = _squash(kw)
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 8

    snapshot, snapshot_warning = load_snapshot(data_dir)
    producer = snapshot["producer"] if snapshot is not None else ""
    roots = {}
    if snapshot is not None:
        roots = _group_roots(snapshot["entries"])
    elif not snapshot_warning:
        legacy = _load_legacy(data_dir)
        if legacy:
            roots = _group_roots(legacy)

    vanilla_by_name = {}
    for row in _load_vanilla():
        name = (row.get("name") or "").strip()
        if name:
            vanilla_by_name.setdefault(name, row)

    results = []
    for name, root in roots.items():
        merged = _merge_with_vanilla(root, vanilla_by_name.get(name))
        score, matched = _score_runtime(merged, tokens, query_norm)
        if score is not None:
            results.append((score, name.lower(), merged, matched))
    for name, row in vanilla_by_name.items():
        if name in roots:
            continue  # 运行时同根已合并，避免 /forge 这类同名重复占位
        score = _score_vanilla(row, tokens, query_norm)
        if score is not None:
            results.append((score, name.lower(), row, []))
    results.sort(key=lambda item: (item[0], item[1]))
    top = results[:limit]

    if not top:
        lines = []
        if snapshot_warning:
            lines.append("⚠️ %s" % snapshot_warning)
        if snapshot is not None:
            lines.append(
                "未找到与「%s」相关的命令。当前已收录 %d 个运行时命令根（含原版命令树）"
                "和 %d 个内置命令。模组命令只有英文命令名与参数语法、没有中文说明："
                "请先把意图提炼成一两个英文概念词（如「陈酿」→ wine、「传送石碑」→ waystone），"
                "多个词用空格隔开、顺序不限（如 quest editing）；仍没命中就换更短的词或英文近义说法，"
                "命中根后再用子命令/参数词细化。内置原版命令照旧支持中文描述搜索。"
                % (keyword, len(roots), len(vanilla_by_name))
            )
        else:
            lines.append(
                "未找到与「%s」相关的命令。内置原版命令支持中文描述搜索；模组命令需服务器侧导出"
                "（/mc_kb_dump 生成 runtime_dump/commands.json）后才会被收录，届时用英文命令名"
                "或参数词查询（多个词用空格隔开、顺序不限）。" % keyword
            )
        return "\n".join(lines)

    lines = []
    if snapshot_warning:
        lines.append("⚠️ %s，本次只返回内置原版命令。" % snapshot_warning)
    lines.append("找到 %d 个匹配「%s」的命令：" % (len(top), keyword))
    has_runtime = False
    for _score, _name, row, matched in top:
        if row.get("kind") == "runtime":
            has_runtime = True
            lines.extend(_format_runtime(row, matched))
        else:
            lines.append(_format_vanilla(row))
    if has_runtime:
        lines.append(_runtime_note(producer))
    if len(results) > limit:
        lines.append("（只显示前 %d 个命令，可用更精确的关键词）" % limit)
    return "\n".join(lines)


def _format_runtime(row: dict, matched: list) -> list:
    cat = _CAT_LABEL.get(row.get("cat"), row.get("cat") or "")
    meta = [cat] if cat else []
    meta.extend(["来源未知", "权限未知"])
    lines = [
        "- /%s — %s（%s）"
        % (row["name"], row.get("desc") or "运行时命令", "，".join(meta)),
    ]
    ordered = list(matched) + [usage for usage in row["usages"] if usage not in matched]
    shown = ordered[:USAGE_PER_ROOT]
    if shown:
        lines.append("  语法：")
        for usage in shown:
            lines.append("    · %s" % usage)
        hidden = len(row["usages"]) - len(shown)
        if hidden > 0:
            lines.append("    （另有 %d 条用法，可用更精确的关键词）" % hidden)
    for hint in row["redirects"]:
        lines.append("  重定向：%s（别名/指向，不是完整可执行路径）" % hint)
    return lines


def _runtime_note(producer: str) -> str:
    if producer == "rcon":
        return (
            "注：运行时语法来自 RCON help，根命令与一级子命令可还原，更深分支是压缩语法"
            "（(a|b)、[x]、...），不能当作完整参数；实际执行还受 RCON 可见性限制。"
        )
    if producer == "kubejs":
        return (
            "注：运行时语法是服务端当前命令树已注册的路径，不代表当前调用者必然可执行"
            "（仍受权限等级与命令来源限制）。"
        )
    return "注：运行时语法来自旧版导出文件，来源与完整性未知。"


def _format_vanilla(row: dict) -> str:
    src = row.get("source", "vanilla")
    src_label = "原版" if src == "vanilla" else src
    level = row.get("level")
    level_label = "，游戏内需 %d 级权限" % level if isinstance(level, int) else ""
    cat = _CAT_LABEL.get(row.get("cat"), row.get("cat") or "")
    return "- /%s — %s\n  语法：%s（%s%s%s）" % (
        row.get("name"),
        row.get("desc"),
        row.get("syntax"),
        src_label,
        "，" + cat if cat else "",
        level_label,
    )
