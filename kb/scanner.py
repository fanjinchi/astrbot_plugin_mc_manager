"""离线扫描 MC 服务端安装（mods/*.jar + kubejs/），还原注册 ID 与中英文名。

移植自研究原型 /home/guigui/mc/.research/prototype/scan_items.py（已在 Farming/zyjd 两台
真实服务器上验证）。裁剪掉置信度、冲突表等研究字段，保留三条关键规则：

1. 两遍扫描：先用 data/ 资源与模型文件名收集"硬 id"作为 known_ids，再扫描语言文件；
   语言文件的 key 可能本身带点号（深层 key），要靠 known_ids 区分整串 id 与子 key。
2. 子 key（.desc / .tooltip / 药水变体等）不能覆盖 base id 的中文名。
3. 名称按层合并：kubejs/assets 资源包覆盖（优先级 2）> jar 自带语言文件（优先级 1）。

数据来源（source 字段，逗号分隔）：
    lang        jar 内 assets/<ns>/lang/{en_us,zh_cn}.json
    kubejs_lang kubejs/assets/**/lang/*.json（整合包自带资源包，游戏内最后生效）
    trans       kubejs/config/english_translation.json 的 registry 段（只给英文）
    tag/recipe/loot   data/<ns>/**.json 里的 id 引用
    model/blockstate  资源文件名（弱证据，但能判定方块有没有物品模型）
    script/script_registry  kubejs 脚本里的字面量 id 与动态注册
"""

import io
import json
import os
import re
import zipfile
from collections import Counter

ID_RE = re.compile(r"^[a-z0-9_.\-]+:[a-z0-9_./\-]+$")
LANG_RE = re.compile(r"^assets/([^/]+)/lang/([^/]+)\.json$", re.I)
NS_KEY_PREFIX = {"item": "item", "block": "block", "entity": "entity", "fluid": "fluid"}
TAG_KIND = {
    "items": "item", "blocks": "block", "entity_types": "entity", "fluids": "fluid",
    "item": "item", "block": "block", "entity_type": "entity", "fluid": "fluid",
}
# 每个 id 的主 kind 优先级（与原型一致）
_KIND_ORDER = ("entity", "fluid", "block", "item")


class ScanResult:
    """一次扫描的结果：rows = id -> 记录；warnings = 人可读告警。"""

    def __init__(self):
        self.rows = {}
        self.mods = {}
        self.warnings = []
        self.stats = {}


class _Collector:
    def __init__(self):
        self.ids = {}
        self.zh = {}
        self.en = {}
        self.zh_layers = {}
        self.en_layers = {}
        self.keymap = {}
        self.subkeys = set()
        self.mods = {}
        self.asset_namespaces = set()
        self.warnings = []
        self.stats = Counter()

    def warn(self, message):
        self.stats["warnings"] += 1
        if len(self.warnings) < 10:
            self.warnings.append(message)

    def touch(self, id_, kind, source):
        """登记一个 id（kind/source 为证据）。"""
        ns, _, path = (id_ or "").partition(":")
        if not ns or not path or not re.match(r"^[a-z0-9_.-]+$", ns) or not re.match(r"^[a-z0-9_./-]+$", path):
            self.stats["invalid_id_skipped"] += 1
            return
        rec = self.ids.get(id_)
        if rec is None:
            rec = self.ids[id_] = {"kinds": set(), "sources": set()}
        if kind:
            rec["kinds"].add(kind)
        rec["sources"].add(source)

    def set_name(self, id_, lang, value, layer, prio):
        """按优先级写入名称；同时记录该 id 出现过名称的层（用于分层覆盖率统计）。"""
        if not value or not isinstance(value, str):
            return
        store = self.zh if lang == "zh" else self.en
        layers = self.zh_layers if lang == "zh" else self.en_layers
        layers.setdefault(id_, set()).add(layer)
        old = store.get(id_)
        if old is None or prio >= old[2]:
            store[id_] = (value, layer, prio)


# ------------------------------------------------------------------ jar 读取


def _open_zip_bytes(data):
    return zipfile.ZipFile(io.BytesIO(data))


def _iter_jars(server_dir, c):
    """yield (jar_name, ZipFile)；含 jar-in-jar 一层嵌套。"""
    mods = os.path.join(server_dir, "mods")
    if not os.path.isdir(mods):
        c.warn("找不到 mods 目录：%s" % mods)
        return
    for fn in sorted(os.listdir(mods)):
        if not fn.lower().endswith(".jar"):
            continue
        p = os.path.join(mods, fn)
        if not os.path.isfile(p):
            continue
        try:
            z = zipfile.ZipFile(p)
        except Exception as e:  # 坏 jar 不能中断整次扫描
            c.warn("无法打开 %s: %s" % (fn, e))
            continue
        c.stats["jars"] += 1
        yield fn, z
        for n in z.namelist():
            if n.lower().endswith(".jar"):
                try:
                    c.stats["nested_jars"] += 1
                    yield fn + "!/" + n, _open_zip_bytes(z.read(n))
                except Exception:
                    pass


def _parse_mods_toml(txt):
    """返回 [[mods]] 段里的 [{modId, displayName, version}]。"""
    out, cur, section = [], None, None
    for line in txt.splitlines():
        s = line.strip()
        m = re.match(r"^\[\[([^\]]+)\]\]", s)
        if m:
            section = m.group(1)
            if section == "mods":
                cur = {}
                out.append(cur)
            else:
                cur = None
            continue
        m = re.match(r"^\[([^\]]+)\]", s)
        if m:
            section = m.group(1)
            cur = None
            continue
        if cur is None:
            continue
        # 值后面常跟行尾注释（modId="alexsmobs" #mandatory），不能锚定到行尾
        m = re.match(r'''^(modId|displayName|version|description|license)\s*=\s*(["'])(.*?)\2''', s)
        if m:
            cur.setdefault(m.group(1), m.group(3))
    return [m for m in out if m.get("modId")]


def _parse_fabric_json(raw):
    try:
        d = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        return None
    if not isinstance(d, dict) or not d.get("id"):
        return None
    return {"modId": d["id"], "displayName": d.get("name") or d["id"], "version": d.get("version", "")}


def _read_json(z, name):
    try:
        raw = z.read(name)
    except Exception:
        return None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return json.loads(raw.decode(enc))
        except Exception:
            continue
    return None


# ------------------------------------------------------------------ jar 扫描


def _scan_mod_meta(c, jar_name, z, names):
    for n in names:
        if n.endswith("META-INF/mods.toml"):
            try:
                txt = z.read(n).decode("utf-8", "replace")
            except Exception:
                continue
            for m in _parse_mods_toml(txt):
                c.mods.setdefault(m["modId"], {
                    "mod_id": m["modId"],
                    "mod_name": m.get("displayName") or m["modId"],
                    "version": m.get("version", ""),
                    "jar": jar_name,
                })
            break
    for n in names:
        if n.endswith("fabric.mod.json"):
            meta = _parse_fabric_json(z.read(n))
            if meta:
                c.mods.setdefault(meta["modId"], {
                    "mod_id": meta["modId"],
                    "mod_name": meta["displayName"],
                    "version": meta["version"],
                    "jar": jar_name,
                })


def _scan_jar(c, jar_name, z, known_ids, skip_lang=False):
    try:
        names = z.namelist()
    except Exception:
        return
    for n in names:
        if n.startswith("assets/") and n.count("/") >= 2:
            c.asset_namespaces.add(n.split("/")[1])

    _scan_mod_meta(c, jar_name, z, names)

    if not skip_lang:
        for n in names:
            m = LANG_RE.match(n)
            if not m:
                continue
            ns, langcode = m.group(1), m.group(2).lower()
            if langcode not in ("en_us", "zh_cn"):
                continue
            d = _read_json(z, n)
            if not isinstance(d, dict):
                c.stats["lang_parse_fail"] += 1
                continue
            c.stats["lang_file_%s" % langcode] += 1
            c.stats["lang_keys_%s" % langcode] += len(d)
            for k, v in d.items():
                if not isinstance(v, str):
                    continue
                seg = k.split(".")
                if len(seg) < 3 or seg[0] not in NS_KEY_PREFIX:
                    c.stats["lang_key_nonreg"] += 1
                    continue
                if seg[1] != ns:
                    # 语言文件所在 jar 的命名空间与 key 里的不一致，仍按 key 解析（与原型一致）
                    c.stats["lang_key_ns_mismatch"] += 1
                keyns, kind, rest = seg[1], NS_KEY_PREFIX[seg[0]], seg[2:]
                cand_short = "%s:%s" % (keyns, rest[0])
                cand_full = "%s:%s" % (keyns, ".".join(rest))
                cand_stripped = "%s:%s" % (keyns, ".".join(rest[:-1])) if len(rest) > 1 else None
                if len(rest) > 1:
                    c.stats["lang_deep_keys"] += 1
                is_subkey = False
                if len(rest) > 1 and cand_full in known_ids:
                    id_ = cand_full
                    c.stats["resolve_full"] += 1
                elif cand_short in known_ids:
                    id_ = cand_short
                    c.stats["resolve_short"] += 1
                    if len(rest) > 1:
                        is_subkey = True
                        c.stats["subkey_dropped"] += 1
                elif cand_stripped and cand_stripped in known_ids:
                    id_ = cand_stripped
                    c.stats["resolve_stripped"] += 1
                    is_subkey = True
                else:
                    id_ = cand_short
                    c.stats["resolve_guess"] += 1
                    if len(rest) > 1:
                        c.stats["resolve_guess_deep"] += 1
                        is_subkey = True
                c.keymap[k] = id_
                c.touch(id_, kind, "lang")
                if is_subkey:
                    c.subkeys.add(k)
                else:
                    c.set_name(id_, "zh" if langcode == "zh_cn" else "en", v, "jar", 1)

    for n in names:
        if not n.startswith("data/"):
            continue
        parts = n.split("/")
        if len(parts) < 4 or not n.endswith(".json"):
            continue
        folder = parts[2]
        if folder == "tags":
            kind_dir = parts[3] if len(parts) > 4 else ""
            kind = TAG_KIND.get(kind_dir)
            if not kind:
                continue
            d = _read_json(z, n)
            if isinstance(d, dict):
                for v in d.get("values", []) or []:
                    if isinstance(v, str) and not v.startswith("#") and ID_RE.match(v):
                        c.touch(v, kind, "tag")
        elif folder == "recipes":
            d = _read_json(z, n)
            if d is not None:
                for id_, kind in _walk_recipe_ids(d):
                    c.touch(id_, kind, "recipe")
        elif folder == "loot_tables":
            d = _read_json(z, n)
            if d is not None:
                for id_, kind in _walk_loot_ids(d):
                    c.touch(id_, kind, "loot")

    for n in names:
        m = re.match(r"^assets/([^/]+)/models/item/(.+)\.json$", n)
        if m:
            if "/" in m.group(2):
                c.stats["asset_subdir_skipped"] += 1
            else:
                c.touch("%s:%s" % (m.group(1), m.group(2)), "item", "model")
        m = re.match(r"^assets/([^/]+)/blockstates/(.+)\.json$", n)
        if m:
            if "/" in m.group(2):
                c.stats["asset_subdir_skipped"] += 1
            else:
                c.touch("%s:%s" % (m.group(1), m.group(2)), "block", "blockstate")


def _walk_recipe_ids(obj):
    """结构化抽取 recipe 里的物品 id（只认 result/ingredients 等语义位置）。"""
    out = []

    def take_result(node):
        if isinstance(node, str):
            if ID_RE.match(node):
                out.append((node, "item"))
        elif isinstance(node, list):
            for x in node:
                take_result(x)
        elif isinstance(node, dict):
            for k in ("item", "id", "result", "output"):
                v = node.get(k)
                if isinstance(v, str) and ID_RE.match(v):
                    out.append((v, "item"))
                elif isinstance(v, (dict, list)):
                    take_result(v)

    def take_ingredient(node):
        if isinstance(node, str):
            if ID_RE.match(node):
                out.append((node, "item"))
        elif isinstance(node, list):
            for x in node:
                take_ingredient(x)
        elif isinstance(node, dict):
            for k in ("item", "id"):
                v = node.get(k)
                if isinstance(v, str) and ID_RE.match(v):
                    out.append((v, "item"))
            for k in ("items", "values", "ingredients", "ingredient", "input", "inputs"):
                if k in node:
                    take_ingredient(node[k])

    if isinstance(obj, dict):
        for k in ("result", "results", "output", "outputs", "byproduct"):
            if k in obj:
                take_result(obj[k])
        for k in ("ingredients", "ingredient", "input", "inputs", "base", "addition",
                  "template", "container", "catalyst", "tools", "key"):
            if k in obj:
                take_ingredient(obj[k])
    return out


def _walk_loot_ids(obj):
    out = []

    def rec(node):
        if isinstance(node, dict):
            t = node.get("type")
            nm = node.get("name")
            if isinstance(nm, str) and ID_RE.match(nm) and isinstance(t, str):
                if t.endswith("item"):
                    out.append((nm, "item"))
                elif t.endswith("entity"):
                    out.append((nm, "entity"))
                elif t.endswith("block"):
                    out.append((nm, "block"))
            for v in node.values():
                rec(v)
        elif isinstance(node, list):
            for v in node:
                rec(v)

    rec(obj)
    return out


# ------------------------------------------------------------------ kubejs


def _resolve_key(c, k):
    """把 lang key 映射到 id；子 key（.desc/.tooltip/药水变体）返回 None。"""
    if k in c.subkeys:
        return None
    if k in c.keymap:
        return c.keymap[k]
    seg = k.split(".")
    if len(seg) == 3 and seg[0] in NS_KEY_PREFIX:
        return "%s:%s" % (seg[1], seg[2])
    return None


def _scan_kubejs(c, server_dir):
    lang_root = os.path.join(server_dir, "kubejs", "assets")
    if os.path.isdir(lang_root):
        for dirpath, _, files in os.walk(lang_root):
            if os.path.basename(dirpath) != "lang":
                continue
            ns = os.path.basename(os.path.dirname(dirpath))
            for f in files:
                if not f.lower().endswith(".json"):
                    continue
                code = f[:-5].lower()
                if code not in ("en_us", "zh_cn"):
                    continue
                p = os.path.join(dirpath, f)
                try:
                    with open(p, encoding="utf-8-sig") as fh:
                        d = json.load(fh)
                except Exception as e:
                    c.warn("读取 kubejs 语言文件失败 %s: %s" % (p, e))
                    continue
                if not isinstance(d, dict):
                    continue
                c.stats["kubejs_lang_files"] += 1
                for k, v in d.items():
                    if not isinstance(v, str):
                        continue
                    id_ = _resolve_key(c, k)
                    if id_ is None:
                        continue
                    c.touch(id_, NS_KEY_PREFIX.get(k.split(".")[0], "item"), "kubejs_lang")
                    c.set_name(id_, "zh" if code == "zh_cn" else "en", v,
                               "kubejs", 2)

    data_root = os.path.join(server_dir, "kubejs", "data")
    if os.path.isdir(data_root):
        for dirpath, _, files in os.walk(data_root):
            rel = os.path.relpath(dirpath, data_root).split(os.sep)
            if len(rel) < 2:
                continue
            folder = rel[1]
            for f in files:
                if not f.endswith(".json"):
                    continue
                p_ = os.path.join(dirpath, f)
                try:
                    with open(p_, encoding="utf-8-sig") as fh:
                        d = json.load(fh)
                except Exception:
                    continue
                c.stats["kubejs_data_files"] += 1
                if folder == "tags":
                    kind = TAG_KIND.get(rel[2]) if len(rel) > 2 else None
                    if not kind or not isinstance(d, dict):
                        continue
                    for v in d.get("values", []) or []:
                        if isinstance(v, str) and not v.startswith("#") and ID_RE.match(v):
                            c.touch(v, kind, "kubejs_data")
                elif folder == "recipes":
                    for id_, kind in _walk_recipe_ids(d):
                        c.touch(id_, kind, "kubejs_data")
                elif folder == "loot_tables":
                    for id_, kind in _walk_loot_ids(d):
                        c.touch(id_, kind, "kubejs_data")

    et = os.path.join(server_dir, "kubejs", "config", "english_translation.json")
    if os.path.isfile(et):
        try:
            with open(et, encoding="utf-8-sig") as fh:
                d = json.load(fh)
            reg = d.get("registry") or {}
            c.stats["trans_registry_keys"] = len(reg)
            for k, v in reg.items():
                if not isinstance(v, str):
                    continue
                id_ = _resolve_key(c, k)
                if id_ is None:
                    continue
                c.touch(id_, NS_KEY_PREFIX.get(k.split(".")[0], "item"), "trans")
                c.set_name(id_, "en", v, "trans", 0.5)
        except Exception as e:
            c.warn("读取 english_translation.json 失败: %s" % e)

    js_root = os.path.join(server_dir, "kubejs")
    if os.path.isdir(js_root):
        for dirpath, dirnames, files in os.walk(js_root):
            dirnames[:] = [d for d in dirnames if d not in ("assets", "data", "config")]
            for f in files:
                if not f.endswith(".js"):
                    continue
                p = os.path.join(dirpath, f)
                try:
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        txt = fh.read()
                except Exception:
                    continue
                c.stats["kubejs_js_files"] += 1
                for m in re.finditer(r"""['"]([a-z0-9_.\-]+:[a-z0-9_./\-]+)['"]""", txt):
                    c.touch(m.group(1), "item", "script")
                for m in re.finditer(r"StartupEvents\.registry\(\s*['\"](\w+)['\"]", txt):
                    reg = m.group(1)
                    tail = txt[m.end():m.end() + 6000]
                    for mm in re.finditer(r"\.create\(\s*['\"]([^'\"]+)['\"]", tail):
                        nm = mm.group(1)
                        if ":" not in nm:
                            nm = "kubejs:" + nm
                        c.touch(nm, reg if reg in ("item", "block", "fluid", "entity_type") else "item",
                                "script_registry")
                        c.stats["kubejs_dynamic_reg"] += 1


# ------------------------------------------------------------------ 汇总


def _finalize(c):
    res = ScanResult()
    res.warnings = list(c.warnings)
    res.mods = c.mods
    for id_ in sorted(c.ids):
        rec = c.ids[id_]
        kinds = rec["kinds"] or {"item"}
        kind = next((k for k in _KIND_ORDER if k in kinds), "item")
        ns, _, path = id_.partition(":")
        zh = c.zh.get(id_)
        en = c.en.get(id_)
        mod = c.mods.get(ns)
        sources = rec["sources"]
        # has_item：item 一定有物品形式；方块有物品模型（BlockItem）才有；
        # entity/fluid 不适用记 NULL。原版方块由 vanilla.py 另行判定。
        if kinds & {"entity", "fluid"}:
            has_item = None
        elif kind == "item" or ("block" in kinds and "model" in sources):
            has_item = 1
        elif "block" in kinds:
            has_item = 0
        else:
            has_item = None
        res.rows[id_] = {
            "id": id_,
            "namespace": ns,
            "path": path,
            "kind": kind,
            "kinds": kinds,
            "sources": sources,
            "name_zh": zh[0] if zh else None,
            "zh_source": zh[1] if zh else None,
            "zh_layers": set(c.zh_layers.get(id_, set())),
            "name_en": en[0] if en else None,
            "en_layers": set(c.en_layers.get(id_, set())),
            "mod_name": mod["mod_name"] if mod else None,
            "cross_ref": ns != "minecraft" and ns not in c.asset_namespaces,
            "origin": "scan",
            "has_item": has_item,
            "has_item_guess": 0,
        }
    res.stats = dict(c.stats)
    res.stats["total"] = len(res.rows)
    return res


def scan(server_dir: str) -> ScanResult:
    """扫描一个 MC 服务端安装目录，返回 ScanResult（不联网、只读）。"""
    c = _Collector()
    known_ids = set()
    # 第一遍：只收 data/ 与资源文件名里的硬 id
    for _name, z in _iter_jars(server_dir, c):
        _scan_jar(c, _name, z, known_ids=set(), skip_lang=True)
    # 第二遍会重新遍历同样的 jar，计数别累加两遍
    jars = c.stats["jars"]
    nested = c.stats.get("nested_jars", 0)
    known_ids = set(c.ids)
    # 第二遍：带上 known_ids 解析语言文件
    for _name, z in _iter_jars(server_dir, c):
        _scan_jar(c, _name, z, known_ids=known_ids)
    c.stats["jars"] = jars
    c.stats["nested_jars"] = nested
    _scan_kubejs(c, server_dir)
    return _finalize(c)
