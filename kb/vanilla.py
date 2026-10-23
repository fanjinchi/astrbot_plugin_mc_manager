"""原版（minecraft: 命名空间）：ID + 英文名离线取自服务端安装，中文按优先级取。

ID 与英文名：Forge 的 libraries/net/minecraft/server/*/server-<ver>-extra.jar（或
-unpacked.jar / bundler 内嵌 jar）自带官方 assets/minecraft/lang/en_us.json。
候选 = item.minecraft.* / block.minecraft.* 且恰好两个点的键；再与同 jar 的
data/minecraft/**/*.json 里的 minecraft:<id> 引用、以及 -srg.jar 的 Items/Blocks 常量池
交叉验证，1.20.1 实测得 1,369 个（987 方块 + 382 物品），离线 0.1 s。

中文：<数据目录>/vanilla/zh_cn-<版本>.json（缓存/服主手放）
      > <mc_client_dir> 客户端（jar 或 assets）
      > 官方按版本下载（vanilla_zh_download，sha1 校验、缓存、失败回退 BMCLAPI）
      > 都没有 → 只建英文。
语言文件**只当字典**用：只拿已确定的 1,369 个 ID 去查键，绝不用它的键生成 ID，
避免下载到重发布/错版本的 lang 污染 ID 集合。
"""

import glob
import hashlib
import io
import json
import os
import re
import struct
import time
import urllib.request
import zipfile

EN_US_PATH = "assets/minecraft/lang/en_us.json"

_MANIFEST_URLS = (
    "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json",
    "https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json",
)
_OBJECT_BASE = "https://resources.download.minecraft.net/%s/%s"
_OBJECT_MIRROR = "https://bmclapi2.bangbang93.com/assets/%s/%s"
_UA = {"User-Agent": "astrbot-mc-manager/1.0 (Minecraft admin plugin)"}
_ZH_INDEX_KEY = "minecraft/lang/zh_cn.json"


class VanillaResult:
    def __init__(self):
        self.rows = {}
        self.stats = {}
        self.warnings = []


# ------------------------------------------------------------------ 版本探测


def detect_version(server_dir: str) -> str:
    """MC 版本：libraries 下的纯版本目录 > logs/latest.log；探测失败返回空串。"""
    libs = os.path.join(server_dir, "libraries", "net", "minecraft", "server")
    if os.path.isdir(libs):
        cands = [d for d in os.listdir(libs) if re.fullmatch(r"\d+(\.\d+)+", d)]
        if cands:
            return sorted(cands, key=lambda v: [int(x) for x in v.split(".")])[-1]
    log = os.path.join(server_dir, "logs", "latest.log")
    if os.path.isfile(log):
        found = ""
        try:
            with open(log, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    m = re.search(r"Starting minecraft server version ([0-9][0-9A-Za-z.\-]*)", line)
                    if m:
                        found = m.group(1).rstrip(".")
        except OSError:
            pass
        if found:
            return found
    return ""


# ------------------------------------------------------------------ 找语言 jar


def _find_lang_jar(server_dir):
    """按 extra → unpacked → bundler 顺序找含 en_us.json 的 jar，返回 (名字, ZipFile)。"""
    base = os.path.join(server_dir, "libraries", "net", "minecraft", "server")
    cands = []
    cands += sorted(glob.glob(os.path.join(base, "*", "server-*-extra.jar")))
    cands += sorted(glob.glob(os.path.join(base, "*", "server-*-unpacked.jar")))
    cands += sorted(glob.glob(os.path.join(base, "*", "server-*.jar")))
    for p in cands:
        try:
            z = zipfile.ZipFile(p)
        except Exception:
            continue
        try:
            if EN_US_PATH in z.namelist():
                return p, z
            for n in z.namelist():
                if n.startswith("META-INF/versions/") and n.endswith(".jar"):
                    try:
                        inner = zipfile.ZipFile(io.BytesIO(z.read(n)))
                    except Exception:
                        continue
                    if EN_US_PATH in inner.namelist():
                        return p + "!" + n, inner
        except Exception:
            continue
    return "", None


def _class_strings(data):
    """读 class 文件常量池里的 UTF8 字符串（不依赖 JVM，纯解析）。"""
    pos = 8
    (cpcount,) = struct.unpack_from(">H", data, pos)
    pos += 2
    out, i = [], 1
    while i < cpcount:
        t = data[pos]
        pos += 1
        if t == 1:
            (ln,) = struct.unpack_from(">H", data, pos)
            pos += 2
            out.append(data[pos:pos + ln].decode("utf-8", "replace"))
            pos += ln
        elif t in (7, 8, 16, 19, 20):
            pos += 2
        elif t == 15:
            pos += 3
        elif t in (3, 4, 9, 10, 11, 12, 17, 18):
            pos += 4
        elif t in (5, 6):
            pos += 8
            i += 1
        else:
            raise ValueError(t)
        i += 1
    return out


def _srg_class_ids(server_dir):
    """从 -srg.jar 的 Items/Blocks 常量池补 datapack 引用不到的 id（刷怪蛋等）。"""
    srg = sorted(glob.glob(os.path.join(server_dir, "libraries", "net", "minecraft", "server", "*", "server-*-srg.jar")))
    ids = set()
    if not srg:
        return ids
    try:
        z = zipfile.ZipFile(srg[0])
    except Exception:
        return ids
    for cls in ("net/minecraft/world/item/Items.class", "net/minecraft/world/level/block/Blocks.class"):
        try:
            for s in _class_strings(z.read(cls)):
                if re.fullmatch(r"[a-z][a-z0-9_]+", s) and not re.fullmatch(r"[fmp]_\d+_", s) and len(s) >= 3:
                    ids.add(s)
        except KeyError:
            pass
    return ids


# ------------------------------------------------------------------ 中文来源


def _http_get(url, timeout=30):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_json(url, timeout=30):
    return json.loads(_http_get(url, timeout).decode("utf-8-sig"))


def _download_zh(version):
    """按版本下载官方 zh_cn.json；返回 (bytes, 来源描述)。失败抛 ValueError。"""
    last_err = None
    for manifest_url in _MANIFEST_URLS:
        try:
            manifest = _http_json(manifest_url)
            entry = next((v for v in manifest.get("versions", []) if v.get("id") == version), None)
            if not entry:
                raise ValueError("版本 %s 不在 manifest 里" % version)
            version_json = _http_json(entry["url"])
            index = _http_json(version_json["assetIndex"]["url"])
            obj = index["objects"][_ZH_INDEX_KEY]
            digest, size = obj["hash"], obj.get("size", 0)
            urls = [_OBJECT_BASE % (digest[:2], digest), _OBJECT_MIRROR % (digest[:2], digest)]
            for url in urls:
                try:
                    raw = _http_get(url)
                except Exception as e:
                    last_err = e
                    continue
                if hashlib.sha1(raw).hexdigest() == digest and (not size or len(raw) == size):
                    source = "官方下载" if "resources.download" in url else "BMCLAPI 下载"
                    return raw, {"source": source, "sha1": digest, "size": len(raw), "version": version}
                last_err = ValueError("zh_cn.json sha1 校验失败: %s" % url)
        except Exception as e:
            last_err = e
            continue
    raise ValueError(str(last_err or "下载 zh_cn.json 失败"))


def _client_candidates(client_dir):
    """客户端安装里可用的版本 jar：[(版本目录名, jar 路径)]。"""
    versions = os.path.join(client_dir, "versions")
    out = []
    if os.path.isdir(versions):
        for d in sorted(os.listdir(versions)):
            p = os.path.join(versions, d, d + ".jar")
            if os.path.isfile(p):
                out.append((d, p))
    return out


def _find_client_jar(client_dir, mc_version):
    """优先版本号完全匹配的客户端 jar；版本不明时若只有一个就用它。"""
    cands = _client_candidates(client_dir)
    if not cands:
        return ""
    if mc_version:
        for d, p in cands:
            if d == mc_version:
                return p
    if len(cands) == 1:
        return cands[0][1]
    return max(cands, key=lambda x: os.path.getmtime(x[1]))[1]


def _client_zh(client_dir, mc_version):
    """从客户端取 zh_cn.json：优先版本 jar，其次 assets 索引对象。返回 (raw, 来源) 或 (None, "")。"""
    jar = _find_client_jar(client_dir, mc_version)
    if jar:
        try:
            with zipfile.ZipFile(jar) as z:
                if _ZH_INDEX_KEY in z.namelist():
                    return z.read(_ZH_INDEX_KEY), "客户端 jar"
        except Exception:
            pass
    indexes = os.path.join(client_dir, "assets", "indexes")
    if os.path.isdir(indexes):
        for name in sorted(os.listdir(indexes)):
            p = os.path.join(indexes, name)
            try:
                idx = json.loads(open(p, encoding="utf-8-sig").read())
                obj = (idx.get("objects") or {}).get(_ZH_INDEX_KEY)
                if not obj:
                    continue
                digest = obj["hash"]
                obj_path = os.path.join(client_dir, "assets", "objects", digest[:2], digest)
                if os.path.isfile(obj_path):
                    return open(obj_path, "rb").read(), "客户端 assets"
            except Exception:
                continue
    return None, ""


def _load_zh_json(raw):
    try:
        d = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def _zh_for(server_dir, data_dir, client_dir, version, allow_download, log):
    """按优先级返回 (zh_dict, 来源描述)；没有可用中文时 (None, "")。"""
    cache = os.path.join(data_dir, "vanilla", "zh_cn-%s.json" % (version or "unknown"))
    if os.path.isfile(cache):
        try:
            with open(cache, encoding="utf-8-sig") as fh:
                d = json.load(fh)
            if isinstance(d, dict):
                return d, "缓存"
        except Exception as e:
            log("原版中文缓存解析失败（忽略）：%s" % e)
    if client_dir and os.path.isdir(client_dir):
        raw, source = _client_zh(client_dir, version)
        d = _load_zh_json(raw) if raw else None
        if d:
            return d, source
    if allow_download and version:
        t0 = time.perf_counter()
        try:
            raw, info = _download_zh(version)
        except Exception as e:
            log("官方原版中文下载失败：%s" % e)
            return None, ""
        d = _load_zh_json(raw)
        if not d:
            log("官方原版中文文件不是合法 JSON（忽略）")
            return None, ""
        try:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            tmp = cache + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(raw)
            os.replace(tmp, cache)
        except OSError as e:
            log("写入原版中文缓存失败（不影响本次重建）：%s" % e)
        log("已下载原版中文 zh_cn-%s.json（%s，%d 字节，%.1f s）"
            % (version, info["source"], info["size"], time.perf_counter() - t0))
        return d, info["source"]
    return None, ""


# ------------------------------------------------------------------ 主流程


def load(server_dir: str, data_dir: str, client_dir: str = "", mc_version: str = "",
         allow_download: bool = True, log=None) -> VanillaResult:
    """构建原版行；任何一步失败都降级返回，不抛异常打断整体重建。"""
    log = log or (lambda msg: None)
    res = VanillaResult()
    jar_name, z = _find_lang_jar(server_dir)
    if not z:
        res.warnings.append("服务端安装里找不到 en_us.json（可能不是 Forge/NeoForge 安装）；原版条目跳过")
        return res
    jar_version = re.search(r"server-(\d+(?:\.\d+)+)-", os.path.basename(jar_name))
    if mc_version and jar_version and jar_version.group(1) != mc_version:
        res.warnings.append("服务端语言文件版本 %s 与配置 mc_version %s 不一致，原版名称可能对不上"
                            % (jar_version.group(1), mc_version))
    try:
        en = json.loads(z.read(EN_US_PATH).decode("utf-8-sig"))
    except Exception as e:
        res.warnings.append("读取 en_us.json 失败：%s" % e)
        return res

    # 1) 候选 ID + 交叉验证
    ids = {
        k.split(".", 2)[2]
        for k in en
        if (k.startswith("item.minecraft.") or k.startswith("block.minecraft.")) and k.count(".") == 2
    }
    refs = set()
    for n in z.namelist():
        if n.startswith("data/minecraft/") and n.endswith(".json"):
            try:
                refs.update(re.findall(r"minecraft:([a-z0-9_]+)", z.read(n).decode("utf-8", "replace")))
            except Exception:
                continue
    cls_ids = _srg_class_ids(server_dir)
    verified = ids & (refs | cls_ids)
    block_ids = {i for i in verified if ("block.minecraft." + i) in en}

    # 2) 实体名（best-effort，未与注册表交叉验证）
    entity_ids = {k.split(".", 2)[2] for k in en
                  if k.startswith("entity.minecraft.") and k.count(".") == 2}

    # 3) 中文
    zh, zh_source = _zh_for(server_dir, data_dir, client_dir, mc_version, allow_download, log)

    def zh_lookup(path, is_block):
        if not zh:
            return None
        key = ("block.minecraft." if is_block else "item.minecraft.") + path
        return zh.get(key)

    # 4) has_item：客户端模型精确 > 服务端掉落表近似 > NULL
    models = set()
    client_jar = _find_client_jar(client_dir, mc_version) if client_dir and os.path.isdir(client_dir) else ""
    if client_jar:
        try:
            with zipfile.ZipFile(client_jar) as cz:
                for n in cz.namelist():
                    m = re.match(r"^assets/minecraft/models/item/([^/]+)\.json$", n)
                    if m:
                        models.add(m.group(1))
        except Exception:
            models = set()
    loot = set()
    for n in z.namelist():
        m = re.match(r"^data/minecraft/loot_tables/blocks/([^/]+)\.json$", n)
        if m:
            loot.add(m.group(1))
    has_client_models = bool(models)
    has_loot = bool(loot)
    if not has_client_models and not has_loot:
        res.warnings.append("既没有客户端模型也没有掉落表，原版方块的 has_item 记为未知")

    total = len(verified) + len(entity_ids)
    zh_hits = 0
    for i in verified:
        is_block = i in block_ids
        if zh_lookup(i, is_block):
            zh_hits += 1
    if zh and verified and zh_hits / len(verified) < 0.95:
        res.warnings.append("原版中文命中率仅 %.1f%%（%d/%d），已忽略该语言文件"
                            % (100.0 * zh_hits / len(verified), zh_hits, len(verified)))
        zh, zh_source = None, ""

    for i in sorted(verified):
        is_block = i in block_ids
        row = {
            "id": "minecraft:" + i,
            "namespace": "minecraft",
            "path": i,
            "kind": "block" if is_block else "item",
            "kinds": {"block"} if is_block else {"item"},
            "sources": {"vanilla"},
            "name_en": en.get(("block.minecraft." if is_block else "item.minecraft.") + i),
            "name_zh": zh_lookup(i, is_block),
            "zh_source": "vanilla" if zh_lookup(i, is_block) else None,
            "zh_layers": {"vanilla"} if zh_lookup(i, is_block) else set(),
            "en_layers": {"vanilla"},
            "mod_name": None,
            "cross_ref": False,
            "origin": "vanilla",
            "has_item": None,
            "has_item_guess": 0,
        }
        if not is_block:
            row["has_item"] = 1
        elif has_client_models:
            row["has_item"] = 1 if i in models else 0
        elif has_loot:
            row["has_item"] = 1 if i in loot else 0
            row["has_item_guess"] = 1
        res.rows[row["id"]] = row

    for i in sorted(entity_ids):
        row_id = "minecraft:" + i
        ent_en = en.get("entity.minecraft." + i)
        ent_zh = (zh or {}).get("entity.minecraft." + i)
        row = res.rows.get(row_id)
        if row is not None:
            # 同 ID 既有物品/方块又有实体（egg / arrow / potion 这类投射物）：
            # 保留物品/方块主类型（查询要能 give），只把实体证据补进 kinds。
            row["kinds"].add("entity")
            if not row.get("name_en") and ent_en:
                row["name_en"] = ent_en
            if not row.get("name_zh") and ent_zh:
                row["name_zh"] = ent_zh
                row["zh_source"] = "vanilla"
                row["zh_layers"].add("vanilla")
            continue
        res.rows[row_id] = {
            "id": row_id,
            "namespace": "minecraft",
            "path": i,
            "kind": "entity",
            "kinds": {"entity"},
            "sources": {"vanilla"},
            "name_en": ent_en,
            "name_zh": ent_zh,
            "zh_source": "vanilla" if ent_zh else None,
            "zh_layers": {"vanilla"} if ent_zh else set(),
            "en_layers": {"vanilla"},
            "mod_name": None,
            "cross_ref": False,
            "origin": "vanilla",
            "has_item": None,
            "has_item_guess": 0,
        }

    res.stats = {
        "jar": jar_name,
        "candidates": len(ids),
        "verified": len(verified),
        "blocks": len(block_ids),
        "items": len(verified) - len(block_ids),
        "entities": len(entity_ids),
        "total": total,
        "zh_source": zh_source,
        "zh_hits": zh_hits if zh else 0,
        "has_item_mode": "client" if has_client_models else ("loot" if has_loot else "none"),
    }
    return res
