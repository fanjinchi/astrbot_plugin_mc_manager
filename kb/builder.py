"""重建编排：扫描 mods → 原版 → CFPA 合并 → zh_cn_extra → 运行时 dump → 写库 → 统计。

口径约定（与 research/08 一致）：
- 分层覆盖率的分母 = 静态扫描出的全部 id（含被 mod 引用但没装的"交叉引用 id"）。
- give 可用 = 不是 entity/fluid，且（item 主类型 或 带物品模型的方块）；有权威
  has_item（原版/运行时 dump）时以它为准。
- CFPA 只对已扫到的 id 生效，不新增 id。
"""

import datetime
import json
import os
import re
import time
from collections import Counter
from typing import Optional

from . import cfpa, scanner, store, vanilla

_ID_RE = re.compile(r"^[a-z0-9_.\-]+:[a-z0-9_./\-]+$")
_DUMP_KINDS = ("item", "block", "entity", "fluid")
_EXTRA_PREFIX = ("item", "block", "entity", "fluid")


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _is_giveable(row) -> bool:
    # 有权威 has_item（原版/运行时 dump）时以它为准：egg/arrow 这类同 ID 投射物也算可 give
    if row.get("has_item") is not None:
        return bool(row["has_item"])
    if row["kinds"] & {"entity", "fluid"}:
        return False
    return row["kind"] == "item" or ("block" in row["kinds"] and "model" in row.get("sources", ()))


def _pct(a: int, b: int) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


# ------------------------------------------------------------------ 各层合并


def _merge_vanilla(rows, van) -> tuple:
    """原版行并入：新增 / 补名称 / 校正主类型 / 补权威 has_item。"""
    added = merged = 0
    for row_id, vrow in van.rows.items():
        row = rows.get(row_id)
        if row is None:
            vrow["mod_name"] = vrow.get("mod_name") or "原版"
            rows[row_id] = vrow
            added += 1
            continue
        merged += 1
        row["kinds"] |= vrow["kinds"]
        if vrow["kind"] in ("item", "block"):
            row["kind"] = vrow["kind"]
        if vrow.get("name_en"):
            row["name_en"] = vrow["name_en"]
            row["en_layers"].add("vanilla")
        if vrow.get("name_zh"):
            row["name_zh"] = vrow["name_zh"]
            row["zh_source"] = "vanilla"
            row["zh_layers"].add("vanilla")
        if vrow.get("has_item") is not None:
            row["has_item"] = vrow["has_item"]
            row["has_item_guess"] = vrow.get("has_item_guess", 0)
        row["sources"].add("vanilla")
        row["mod_name"] = row.get("mod_name") or "原版"
    return added, merged


def _apply_cfpa(rows, zh_map) -> tuple:
    """CFPA 名称按 design §3.1 的优先级合并：覆盖 jar 自带名，但不覆盖 kubejs/extra/原版。"""
    applied = kept = 0
    for row_id, text in zh_map.items():
        row = rows.get(row_id)
        if row is None:
            continue
        if row.get("zh_source") in (None, "jar"):
            row["name_zh"] = text
            row["zh_source"] = "cfpa"
            row["zh_layers"].add("cfpa")
            applied += 1
        else:
            kept += 1
    return applied, kept


def _extra_key_to_id(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    if key.count(".") == 2 and key.split(".")[0] in _EXTRA_PREFIX:
        seg = key.split(".")
        return seg[1] + ":" + seg[2]
    if ":" in key:
        return key
    return ""


def _apply_extra(rows, data_dir, warnings) -> dict:
    path = os.path.join(data_dir, "zh_cn_extra.json")
    info = {"path": path, "applied": 0, "ignored": 0, "error": ""}
    if not os.path.isfile(path):
        return info
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except Exception as e:
        info["error"] = str(e)
        warnings.append("zh_cn_extra.json 解析失败，已跳过：%s" % e)
        return info
    if not isinstance(data, dict):
        info["error"] = "顶层不是 JSON 对象"
        warnings.append("zh_cn_extra.json 顶层必须是 {完整ID: 中文名} 对象，已跳过")
        return info
    for key, value in data.items():
        row_id = _extra_key_to_id(key)
        row = rows.get(row_id) if row_id else None
        if row is None or not isinstance(value, str) or not value.strip():
            info["ignored"] += 1
            continue
        row["name_zh"] = value.strip()
        row["zh_source"] = "extra"
        row["zh_layers"].add("extra")
        info["applied"] += 1
    return info


def _dump_id(raw) -> str:
    """运行时 dump 的 id 形如 ResourceKey[minecraft:item / ns:path]；也兼容裸 id。"""
    if not isinstance(raw, str):
        return ""
    m = re.search(r"/\s*([a-z0-9_.\-]+:[a-z0-9_./\-]+)\s*\]", raw)
    if m:
        return m.group(1)
    return raw if _ID_RE.match(raw) else ""


def _load_runtime_dumps(server_dir: str, data_dir: str, rows) -> dict:
    """合并 <服务端>/runtime_dump 与 <数据目录>/runtime_dump 下的 jsonl（同名取 mtime 新）。"""
    info = {"files": 0, "new": 0, "updated": 0, "has_item": 0}
    files = {}
    for d in (os.path.join(server_dir, "runtime_dump"), os.path.join(data_dir, "runtime_dump")):
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.lower().endswith(".jsonl"):
                continue
            p = os.path.join(d, fn)
            if os.path.getsize(p) == 0:
                continue
            if fn not in files or os.path.getmtime(p) > os.path.getmtime(files[fn]):
                files[fn] = p
    if not files:
        return info
    dump_items, dump_blocks = set(), set()
    for fn, path in files.items():
        stem = fn[:-6].lower()
        default_kind = stem if stem in _DUMP_KINDS else ""
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        info["files"] += 1
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                row_id = _dump_id(obj.get("id"))
                if not row_id:
                    continue
                kind = obj.get("kind") or default_kind
                if kind not in _DUMP_KINDS:
                    continue
                resolved = obj.get("resolved") if isinstance(obj.get("resolved"), str) else ""
                row = rows.get(row_id)
                if row is None:
                    ns, _, path_part = row_id.partition(":")
                    row = rows[row_id] = {
                        "id": row_id,
                        "namespace": ns,
                        "path": path_part,
                        "kind": kind,
                        "kinds": {kind},
                        "sources": {"dump"},
                        "name_en": resolved or None,
                        "name_zh": None,
                        "zh_source": None,
                        "zh_layers": set(),
                        "en_layers": {"dump"} if resolved else set(),
                        "mod_name": None,
                        "cross_ref": False,
                        "origin": "dump",
                        "has_item": None,
                        "has_item_guess": 0,
                    }
                    info["new"] += 1
                else:
                    info["updated"] += 1
                    row["kinds"].add(kind)
                    # 不重算 kind：保留扫描/原版已定的主类型（egg/arrow 这类同 ID 投射物保持 item）
                    if resolved:
                        row["name_en"] = resolved
                        row["en_layers"].add("dump")
                if kind == "item":
                    dump_items.add(row_id)
                elif kind == "block":
                    dump_blocks.add(row_id)
    # 运行时注册表是权威：item 注册表里有 = 可 give；只有 block = 不可 give
    for row_id in dump_items:
        rows[row_id]["has_item"] = 1
        rows[row_id]["has_item_guess"] = 0
        info["has_item"] += 1
    for row_id in dump_blocks - dump_items:
        rows[row_id]["has_item"] = 0
        rows[row_id]["has_item_guess"] = 0
        info["has_item"] += 1
    return info


# ------------------------------------------------------------------ 统计


def _scan_stats(scan_rows, cfpa_ids) -> dict:
    """research/08 口径的分层覆盖率（分母 = 静态扫描 id 全集）。"""
    n = len(scan_rows)
    give_rows = [r for r in scan_rows if _is_giveable(r)]

    def zh_jar(r):
        return "jar" in r["zh_layers"]

    def zh_jk(r):
        return bool(r["zh_layers"] & {"jar", "kubejs"})

    def zh_union(r):
        return bool(r["zh_layers"]) or r["id"] in cfpa_ids

    def zh_jar_cfpa(r):
        return zh_jar(r) or r["id"] in cfpa_ids

    return {
        "n": n,
        "zh_jar": sum(1 for r in scan_rows if zh_jar(r)),
        "zh_jar_kubejs": sum(1 for r in scan_rows if zh_jk(r)),
        "zh_jar_cfpa": sum(1 for r in scan_rows if zh_jar_cfpa(r)),
        "zh_final": sum(1 for r in scan_rows if zh_union(r)),
        "give": len(give_rows),
        "give_zh_jar": sum(1 for r in give_rows if zh_jar(r)),
        "give_zh_final": sum(1 for r in give_rows if zh_union(r)),
        "cross_ref": sum(1 for r in scan_rows if r.get("cross_ref")),
    }


def _pct_fields(d: dict) -> dict:
    out = dict(d)
    n = d.get("n") or 0
    give = d.get("give") or 0
    out["zh_jar_pct"] = _pct(d.get("zh_jar", 0), n)
    out["zh_jar_kubejs_pct"] = _pct(d.get("zh_jar_kubejs", 0), n)
    out["zh_jar_cfpa_pct"] = _pct(d.get("zh_jar_cfpa", 0), n)
    out["zh_final_pct"] = _pct(d.get("zh_final", 0), n)
    out["give_zh_jar_pct"] = _pct(d.get("give_zh_jar", 0), give)
    out["give_zh_final_pct"] = _pct(d.get("give_zh_final", 0), give)
    return out


def _final_stats(rows) -> dict:
    rows = list(rows.values())
    n = len(rows)
    # 按落库的 kind 统计，保证回执数字与库里一致（同 ID 投射物已被原版行校正为 item）
    kinds = Counter(r["kind"] for r in rows)
    give = [r for r in rows if _is_giveable(r)]
    zh_rows = [r for r in rows if r.get("name_zh")]
    by_source = Counter(r.get("zh_source") or "none" for r in zh_rows)
    return {
        "total": n,
        "kinds": dict(kinds),
        "giveable": len(give),
        "zh": {
            "total": len(zh_rows),
            "pct": _pct(len(zh_rows), n),
            "jar": by_source.get("jar", 0),
            "kubejs": by_source.get("kubejs", 0),
            "cfpa": by_source.get("cfpa", 0),
            "extra": by_source.get("extra", 0),
            "vanilla": by_source.get("vanilla", 0),
        },
        "give_zh": {"total": sum(1 for r in give if r.get("name_zh")),
                    "pct": _pct(sum(1 for r in give if r.get("name_zh")), len(give))},
        "no_name": sum(1 for r in rows if not r.get("name_zh") and not r.get("name_en")),
    }


# ------------------------------------------------------------------ 主流程


def rebuild(server_dir: str, data_dir: str, db_path: Optional[str] = None, mc_version: str = "",
            client_dir: str = "", vanilla_zh_download: bool = True,
            cfpa_auto_download: bool = True, log=None) -> dict:
    """全量重建知识库，返回统计 dict；配置错误抛 ValueError（由门面转成中文回执）。"""
    log = log or (lambda msg: None)
    server_dir = (server_dir or "").strip()
    if not server_dir:
        raise ValueError("未配置 mc_server_dir（MC 服务器根目录），无法扫描 mods/")
    if not os.path.isdir(server_dir):
        raise ValueError("mc_server_dir 不存在或不是目录：%s" % server_dir)
    if not os.path.isdir(os.path.join(server_dir, "mods")):
        raise ValueError("目录下没有 mods/，可能不是 MC 服务端根目录：%s" % server_dir)
    data_dir = data_dir or os.getcwd()
    db_path = db_path or os.path.join(data_dir, "items.db")
    t0 = time.perf_counter()
    warnings = []

    # 1) 静态扫描
    log("扫描 mods/ 与 kubejs/ ...")
    t_scan = time.perf_counter()
    scan = scanner.scan(server_dir)
    scan_rows = list(scan.rows.values())
    log("扫描完成：%d 个 ID（%d 个 jar，%.1f s）"
        % (len(scan_rows), scan.stats.get("jars", 0), time.perf_counter() - t_scan))
    warnings.extend(scan.warnings)
    rows = scan.rows

    # 2) MC 版本 + CFPA（只对已扫 id 生效）
    version = (mc_version or "").strip() or vanilla.detect_version(server_dir)
    if not version:
        warnings.append("无法自动探测 MC 版本（服务器 libraries/ 与 logs/latest.log 均未找到），"
                        "请配置 mc_version；原版中文与 CFPA 汉化会跳过")
    known = set(rows)
    cfpa_result = cfpa.load(version, data_dir, known, allow_download=cfpa_auto_download, log=log)
    warnings.extend(cfpa_result.warnings)
    # 验收口径的扫描统计必须在合并原版之前算：原版会就地修改行对象的 has_item/kinds
    scan_stats = _pct_fields(_scan_stats(scan_rows, set(cfpa_result.zh)))

    # 3) 原版 + CFPA 名称合并
    van = vanilla.load(server_dir, data_dir, client_dir=client_dir, mc_version=version,
                       allow_download=vanilla_zh_download, log=log)
    warnings.extend(van.warnings)
    van_added, van_merged = _merge_vanilla(rows, van)
    cfpa_applied, cfpa_kept = _apply_cfpa(rows, cfpa_result.zh)

    # 4) 服主自定义补充
    extra_info = _apply_extra(rows, data_dir, warnings)

    # 5) 运行时 dump（权威）
    dump_info = _load_runtime_dumps(server_dir, data_dir, rows)
    kubejs_hint = os.path.isdir(os.path.join(server_dir, "kubejs")) and not dump_info.get("files")
    for row in rows.values():
        if row["namespace"] == "minecraft" and not row.get("mod_name"):
            row["mod_name"] = "原版"

    # 6) 统计 + 落库
    stats = _final_stats(rows)
    if not cfpa_result.zh:
        if not cfpa_auto_download:
            cfpa_note = "已关闭自动下载，且数据目录 cfpa/ 里没有 zip"
        elif not version:
            cfpa_note = "未探测到 MC 版本"
        elif cfpa.package_names(version) is None:
            cfpa_note = "MC %s 没有官方 CFPA 版本包" % version
        else:
            cfpa_note = "获取失败，可手动放置 zip 到数据目录 cfpa/"
    else:
        cfpa_note = ""
    stats.update({
        "kubejs_hint": kubejs_hint,
        "build_time": _now(),
        "elapsed": round(time.perf_counter() - t0, 2),
        "mc_version": version,
        "server_dir": server_dir,
        "client_dir": client_dir,
        "mods": len(scan.mods),
        "jars": scan.stats.get("jars", 0),
        "scan": scan_stats,
        "vanilla": dict(van.stats, merged=van_merged, added=van_added),
        "cfpa": {
            "note": cfpa_note,
            "name": cfpa_result.info.get("name", ""),
            "tag": cfpa_result.info.get("tag", ""),
            "md5": cfpa_result.info.get("md5", ""),
            "mapped": len(cfpa_result.zh),
            "applied": cfpa_applied,
            "kept_kubejs_or_extra": cfpa_kept,
            "filter": cfpa_result.stats,
        },
        "extra": extra_info,
        "dump": dump_info,
        "warnings": warnings[:20],
    })
    meta = {
        "schema_version": store.SCHEMA_VERSION,
        "build_time": stats["build_time"],
        "mc_version": version,
        "stats": stats,
    }
    store.write(db_path, rows.values(), meta)
    log("知识库写入完成：%d 条（%.1f s）" % (len(rows), time.perf_counter() - t0))
    return stats
