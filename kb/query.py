"""知识库的对外文案：查询结果 / 重建回执 / 状态。"""

from typing import Optional

_KIND_LABEL = {"item": "物品", "block": "方块", "fluid": "流体", "entity": "实体"}
_CFPA_ATTRIBUTION = (
    "翻译数据来自 CFPA Minecraft-Mod-Language-Package（CC BY-NC-SA 4.0）"
    "：https://github.com/CFPAOrg/Minecraft-Mod-Language-Package"
)
_MOJANG_NOTE = "原版名称来自本机安装的官方语言文件（运行时下载/本机读取，插件不分发任何 Minecraft 资源）。"


def format_not_built() -> str:
    return "物品知识库尚未构建。请让管理员运行 /mc_kb_rebuild 重建后再查询。"


def format_search(keyword: str, rows: list, limit: int = 10) -> str:
    if not rows:
        return ("知识库未收录「%s」。若这是原版物品（如 diamond_sword），可直接用原版 ID 调用 "
                "give_item，或用 execute_command 执行 fill 命令。" % keyword)
    lines = ["找到 %d 个匹配「%s」的条目：" % (len(rows), keyword)]
    for row in rows:
        lines.append("- " + _format_row(row))
    if len(rows) >= limit:
        lines.append("（只显示前 %d 条，可用更精确的关键词）" % limit)
    return "\n".join(lines)


def _format_row(row: dict) -> str:
    names = []
    if row.get("name_zh"):
        names.append(row["name_zh"])
    if row.get("name_en") and row["name_en"] != row.get("name_zh"):
        names.append(row["name_en"])
    label = " / ".join(names) if names else "（无译名）"
    kind = _KIND_LABEL.get(row.get("kind"), row.get("kind") or "未知")
    mod = row.get("mod_name") or row.get("namespace") or ""
    return "%s — %s（%s，%s）%s" % (row["item_id"], label, mod, kind, _usage_hint(row))


def _usage_hint(row: dict) -> str:
    kind = row.get("kind")
    if kind == "entity":
        return "；用于 summon_entity"
    if kind == "fluid":
        return "；流体，填充时用对应方块 ID"
    has_item = row.get("has_item")
    if has_item == 1:
        if row.get("has_item_guess"):
            return "；推测可 give（依据掉落表，未验证），也可用 execute_command 执行 fill"
        return "；可 give"
    if has_item == 0:
        return "；无物品形式，只能 fill（execute_command）"
    return "；可尝试 give，失败则只能 fill（execute_command）"


def format_status(meta: Optional[dict]) -> str:
    if not meta or not meta.get("stats"):
        return "📚 物品知识库尚未构建。运行 /mc_kb_rebuild 开始构建。"
    st = meta["stats"]
    kinds = st.get("kinds", {})
    zh = st.get("zh", {})
    van = st.get("vanilla", {})
    cf = st.get("cfpa", {})
    lines = [
        "📚 物品知识库状态",
        "构建时间：%s（耗时 %.1fs）" % (st.get("build_time", "?"), st.get("elapsed", 0)),
        "MC 版本：%s｜服务器目录：%s" % (st.get("mc_version") or "未知", st.get("server_dir", "?")),
        "条目：%d（物品 %d / 方块 %d / 流体 %d / 实体 %d）" % (
            st.get("total", 0), kinds.get("item", 0), kinds.get("block", 0),
            kinds.get("fluid", 0), kinds.get("entity", 0)),
        "中文：%d 条（%.1f%%）" % (zh.get("total", 0), zh.get("pct", 0.0)),
        "give 可用：%d 条，其中有中文 %d 条（%.1f%%）" % (
            st.get("giveable", 0), st.get("give_zh", {}).get("total", 0),
            st.get("give_zh", {}).get("pct", 0.0)),
        "原版：%d 条（方块 %d / 物品 %d / 实体名 %d），中文来源 %s" % (
            van.get("total", 0), van.get("blocks", 0), van.get("items", 0),
            van.get("entities", 0), van.get("zh_source") or "无（仅英文）"),
        "CFPA：%s %s" % (cf.get("name") or "未使用", cf.get("tag") or ""),
    ]
    if st.get("warnings"):
        lines.append("告警 %d 条（最新：%s）" % (len(st["warnings"]), st["warnings"][-1]))
    return "\n".join(lines)


def format_rebuild(stats: dict) -> str:
    kinds = stats.get("kinds", {})
    zh = stats.get("zh", {})
    scan = stats.get("scan", {})
    van = stats.get("vanilla", {})
    cf = stats.get("cfpa", {})
    lines = [
        "✅ 物品知识库重建完成（%.1fs）" % stats.get("elapsed", 0),
        "条目：%d（物品 %d / 方块 %d / 流体 %d / 实体 %d）" % (
            stats.get("total", 0), kinds.get("item", 0), kinds.get("block", 0),
            kinds.get("fluid", 0), kinds.get("entity", 0)),
        "中文：%d 条（%.1f%%）＝ jar %d + kubejs 资源包 %d + CFPA %d + 自定义 %d + 原版 %d" % (
            zh.get("total", 0), zh.get("pct", 0.0), zh.get("jar", 0), zh.get("kubejs", 0),
            zh.get("cfpa", 0), zh.get("extra", 0), zh.get("vanilla", 0)),
        "give 可用：%d 条，其中有中文 %d 条（%.1f%%）" % (
            stats.get("giveable", 0), stats.get("give_zh", {}).get("total", 0),
            stats.get("give_zh", {}).get("pct", 0.0)),
        "静态扫描（验收口径）：%d 条 ID；仅 jar 自带中文 %d（%.1f%%）｜加 kubejs %d（%.1f%%）｜加 CFPA %d（%.1f%%）" % (
            scan.get("n", 0), scan.get("zh_jar", 0), scan.get("zh_jar_pct", 0.0),
            scan.get("zh_jar_kubejs", 0), scan.get("zh_jar_kubejs_pct", 0.0),
            scan.get("zh_final", 0), scan.get("zh_final_pct", 0.0)),
        "静态扫描的 give 子集：%d 条，其中中文 %d（%.1f%%）" % (
            scan.get("give", 0), scan.get("give_zh_final", 0), scan.get("give_zh_final_pct", 0.0)),
        "原版：%d 条（方块 %d / 物品 %d / 实体名 %d），中文 %s" % (
            van.get("total", 0), van.get("blocks", 0), van.get("items", 0),
            van.get("entities", 0), van.get("zh_source") or "无（仅英文）"),
    ]
    if cf.get("name"):
        lines.append("CFPA：%s %s，映射 %d 条（覆盖/补全条目 %d，保留 kubejs/自定义 %d）" % (
            cf.get("name"), cf.get("tag") or "", cf.get("mapped", 0),
            cf.get("applied", 0), cf.get("kept_kubejs_or_extra", 0)))
    else:
        lines.append("CFPA：未使用（%s）" % (cf.get("note") or "未获取到汉化包"))
    lines.append("交叉引用 ID：%d 条（被 mod 引用但对应 mod 未安装，游戏内不存在）" % scan.get("cross_ref", 0))
    extra = stats.get("extra") or {}
    if extra.get("applied") or extra.get("ignored"):
        lines.append("自定义补充：应用 %d 条，忽略 %d 条（未匹配已扫到的 ID 或值为空）"
                     % (extra.get("applied", 0), extra.get("ignored", 0)))
    if stats.get("kubejs_hint"):
        lines.append("提示：检测到 kubejs/。如需补齐动态注册物品，按 README「运行时 dump」导出 "
                     "runtime_dump/*.jsonl 后重建即可合并")
    if stats.get("dump", {}).get("files"):
        lines.append("运行时 dump：%d 个文件，合并 %d 次（权威 has_item 覆盖 %d 条）" % (
            stats["dump"]["files"], stats["dump"].get("updated", 0) + stats["dump"].get("new", 0),
            stats["dump"].get("has_item", 0)))
    if stats.get("warnings"):
        lines.append("⚠️ 告警：")
        for msg in stats["warnings"][:6]:
            lines.append("  • " + msg)
    lines.append(_CFPA_ATTRIBUTION)
    lines.append(_MOJANG_NOTE)
    return "\n".join(lines)
