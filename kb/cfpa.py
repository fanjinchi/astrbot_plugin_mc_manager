"""CFPA 汉化资源包：按服务器版本选包、下载（GitHub → BMCLAPI 回退）、md5 校验、解析。

包名是**离散映射表**，不是"主版本取前两位"（1.13/1.14/1.15/1.17 官方没有包）。
发布源用 GitHub /releases/latest（实测 tag = autobuild，全版本资产齐全），不用按时间
最新的 Snapshot（实测它只带 1.21 一个版本）。md5 资产名是 <版本>.md5（如 1.20.md5），
内容是**大写** hex，比较时必须 lower()。

合并规则（与 research/08 实测口径一致）：只读 assets/*/lang/zh_cn.json；剔除空值、
.name 后缀、含冒号的 key、非 item/block/entity/fluid 前缀；按整串 id > 首段 id >
去掉末段 的顺序映射到**已扫到的 id**（不新增 id，否则会把没装的 mod 灌进库）。
"""

import hashlib
import json
import os
import re
import time
import urllib.request
import zipfile
from typing import Optional, Tuple

_RELEASES_API = "https://api.github.com/repos/CFPAOrg/Minecraft-Mod-Language-Package/releases/latest"
_MIRROR_DIR = "https://bmclapi2.bangbang93.com/mirrors/i18n-update-mod/"
_UA = {"User-Agent": "astrbot-mc-manager/1.0 (Minecraft admin plugin)"}
_PREFIX = {"item": "item", "block": "block", "entity": "entity", "fluid": "fluid"}

# 精确版本表；16/18/19/20/21 走通用规则 -1-<主>-<次>
_EXACT = {
    "1.6": ("Minecraft-Mod-Language-Modpack-1-6.zip", "1.6.md5"),
    "1.10.2": ("Minecraft-Mod-Language-Modpack-1-10-2.zip", "1.10.2.md5"),
    "1.12.2": ("Minecraft-Mod-Language-Modpack.zip", "1.12.2.md5"),
}
_GENERIC_MAJORS = {"1.6", "1.16", "1.18", "1.19", "1.20", "1.21", "26.1"}
# 官方没有包的版本，别构造 URL 硬下
_UNSUPPORTED = {"1.13", "1.14", "1.15", "1.17"}


def package_names(version: str) -> Optional[Tuple[str, str]]:
    """返回 (zip 名, md5 名)；该版本没有 CFPA 包时返回 None。"""
    v = (version or "").strip()
    if not v:
        return None
    if v in _EXACT:
        return _EXACT[v]
    m = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", v)
    if not m:
        return None
    short = "%s.%s" % (m.group(1), m.group(2))
    if short in _UNSUPPORTED:
        return None
    if short in _GENERIC_MAJORS:
        return ("Minecraft-Mod-Language-Modpack-%s-%s.zip" % (m.group(1), m.group(2)),
                short + ".md5")
    return None


class CfpaResult:
    def __init__(self):
        self.zh = {}
        self.stats = {}
        self.warnings = []
        self.info = {}


def _http_get(url, timeout=60):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _md5_hex(raw):
    return hashlib.md5(raw).hexdigest()


def _md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _remote_md5(md5_name, log):
    """从 GitHub autobuild 或镜像目录取远端 md5（32B）；都失败返回空串。"""
    try:
        data = json.loads(_http_get(_RELEASES_API, timeout=30).decode("utf-8-sig"))
        assets = {a.get("name"): a.get("browser_download_url") for a in data.get("assets", [])}
        if md5_name in assets:
            return _read_remote_md5(assets[md5_name])
    except Exception as e:
        log("读取远端 md5 失败：%s" % e)
    try:
        listing = _http_get(_MIRROR_DIR, timeout=30).decode("utf-8", "replace")
        for href in re.findall(r'href="([^"]+)"', listing):
            if href.rstrip("/").split("/")[-1] == md5_name:
                url = href if href.startswith("http") else _MIRROR_DIR.rstrip("/") + "/" + href.rstrip("/").split("/")[-1]
                return _read_remote_md5(url)
    except Exception as e:
        log("从镜像读取 md5 失败：%s" % e)
    return ""


def _read_remote_md5(url):
    text = _http_get(url, timeout=20).decode("utf-8", "replace").strip().lower()
    m = re.search(r"[0-9a-f]{32}", text)
    return m.group(0) if m else ""


def _try_download(urls, expected_md5, cache_zip, log):
    """依次尝试下载 zip 并校验 md5；成功写缓存并返回 bytes。"""
    for url in urls:
        try:
            raw = _http_get(url, timeout=120)
        except Exception as e:
            log("下载失败 %s: %s" % (url, e))
            continue
        if expected_md5 and _md5_hex(raw) != expected_md5:
            log("md5 不匹配，丢弃 %s" % url)
            continue
        try:
            tmp = cache_zip + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(raw)
            os.replace(tmp, cache_zip)
        except OSError as e:
            log("写入 CFPA 缓存失败（不影响本次重建）：%s" % e)
        return raw
    return None


def _github_download(zip_name, md5_name, cache_zip, log):
    data = json.loads(_http_get(_RELEASES_API, timeout=30).decode("utf-8-sig"))
    assets = {a.get("name"): a.get("browser_download_url") for a in data.get("assets", [])}
    if zip_name not in assets:
        log("GitHub 最新发布里没有 %s" % zip_name)
        return None, {}
    expected = ""
    if md5_name in assets:
        try:
            expected = _read_remote_md5(assets[md5_name])
        except Exception as e:
            log("读取 md5 失败（继续下载）：%s" % e)
    raw = _try_download([assets[zip_name]], expected, cache_zip, log)
    if raw is None:
        return None, {}
    return raw, {"tag": data.get("tag_name", ""), "md5": expected or _md5_hex(raw)}


def _mirror_download(zip_name, md5_name, cache_zip, log):
    listing = _http_get(_MIRROR_DIR, timeout=30).decode("utf-8", "replace")
    hrefs = re.findall(r'href="([^"]+)"', listing)
    zip_url = md5_url = ""
    for href in hrefs:
        base = href.rstrip("/").split("/")[-1]
        if base == zip_name:
            zip_url = href if href.startswith("http") else _MIRROR_DIR.rstrip("/") + "/" + base
        elif base == md5_name:
            md5_url = href if href.startswith("http") else _MIRROR_DIR.rstrip("/") + "/" + base
    if not zip_url:
        log("BMCLAPI 镜像里没有 %s" % zip_name)
        return None, {}
    expected = ""
    if md5_url:
        try:
            expected = _read_remote_md5(md5_url)
        except Exception as e:
            log("读取镜像 md5 失败（继续下载）：%s" % e)
    raw = _try_download([zip_url], expected, cache_zip, log)
    if raw is None:
        return None, {}
    return raw, {"tag": "bmclapi", "md5": expected or _md5_hex(raw)}


def _manual_zips(cache_dir):
    if not os.path.isdir(cache_dir):
        return []
    return sorted(
        (os.path.join(cache_dir, f) for f in os.listdir(cache_dir) if f.lower().endswith(".zip")),
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )


def fetch_zip(version: str, data_dir: str, allow_download: bool = True, log=None) -> Tuple[str, dict]:
    """取 CFPA zip：数据目录里的手动包优先，其次按版本下载。返回 (路径, 信息) 或 (None, {})。"""
    log = log or (lambda msg: None)
    cache_dir = os.path.join(data_dir, "cfpa")
    os.makedirs(cache_dir, exist_ok=True)
    names = package_names(version)
    if names:
        zip_name, md5_name = names
        cached = os.path.join(cache_dir, zip_name)
        local_md5_path = os.path.join(cache_dir, zip_name + ".md5")
        local_md5 = ""
        if os.path.isfile(local_md5_path):
            try:
                local_md5 = open(local_md5_path, encoding="utf-8").read().strip().lower()
            except OSError:
                local_md5 = ""
        if os.path.isfile(cached):
            if not allow_download:
                return cached, {"name": zip_name, "md5": local_md5, "tag": "本地缓存"}
            actual = _md5_file(cached)
            remote = _remote_md5(md5_name, log)
            if remote and actual == remote:
                log("CFPA 缓存已是最新（md5 %s），跳过下载" % remote)
                return cached, {"name": zip_name, "md5": remote, "tag": "本地缓存"}
            if not remote and local_md5 and local_md5 == actual:
                return cached, {"name": zip_name, "md5": local_md5, "tag": "本地缓存"}
        if allow_download:
            t0 = time.perf_counter()
            raw, info = None, {}
            try:
                raw, info = _github_download(zip_name, md5_name, cached, log)
            except Exception as e:
                log("GitHub 取 CFPA 包失败：%s" % e)
            if raw is None:
                try:
                    raw, info = _mirror_download(zip_name, md5_name, cached, log)
                except Exception as e:
                    log("BMCLAPI 镜像取 CFPA 包失败：%s" % e)
            if raw is not None:
                try:
                    with open(local_md5_path, "w", encoding="utf-8") as fh:
                        fh.write(info.get("md5", ""))
                except OSError:
                    pass
                info.update({"name": zip_name, "size": len(raw),
                             "seconds": round(time.perf_counter() - t0, 2)})
                log("已获取 CFPA 包 %s（%s，%d 字节，%.1f s）"
                    % (zip_name, info.get("tag", ""), len(raw), info["seconds"]))
                return cached, info
            if os.path.isfile(cached):
                log("在线获取失败，改用已有缓存 %s" % cached)
                return cached, {"name": zip_name, "md5": local_md5, "tag": "本地缓存"}
    elif version and package_names(version) is None:
        log("MC %s 没有对应的 CFPA 版本包，跳过自动下载（可手动放置 zip 到 %s）" % (version, cache_dir))
    manual = _manual_zips(cache_dir)
    if manual:
        log("使用数据目录里的 CFPA 包：%s" % os.path.basename(manual[0]))
        return manual[0], {"name": os.path.basename(manual[0]), "tag": "手动放置"}
    return None, {}


def parse_zip(zip_path: str, known_ids: set) -> CfpaResult:
    """解析 CFPA 包，返回只映射到 known_ids 的 {id: 中文} 与过滤统计。"""
    res = CfpaResult()
    res.zh = {}
    st = res.stats = {
        "files": 0, "keys": 0, "empty_value": 0, "drop_dot_name": 0, "drop_colon": 0,
        "drop_prefix": 0, "subkey_dropped": 0, "unmatched": 0, "mapped_ids": 0, "conflict": 0,
    }
    try:
        z = zipfile.ZipFile(zip_path)
    except Exception as e:
        res.warnings.append("CFPA 包无法打开：%s" % e)
        return res
    with z:
        for n in z.namelist():
            if not n.lower().endswith("/lang/zh_cn.json"):
                continue
            st["files"] += 1
            try:
                d = json.loads(z.read(n).decode("utf-8-sig"))
            except Exception:
                st["parse_fail"] = st.get("parse_fail", 0) + 1
                continue
            if not isinstance(d, dict):
                st["not_dict"] = st.get("not_dict", 0) + 1
                continue
            for k, v in d.items():
                st["keys"] += 1
                if not isinstance(v, str) or not v.strip():
                    st["empty_value"] += 1
                    continue
                if k.endswith(".name"):
                    st["drop_dot_name"] += 1
                    continue
                if ":" in k:
                    st["drop_colon"] += 1
                    continue
                seg = k.split(".")
                if len(seg) < 3 or seg[0] not in _PREFIX:
                    st["drop_prefix"] += 1
                    continue
                keyns, rest = seg[1], seg[2:]
                full = keyns + ":" + ".".join(rest)
                short = keyns + ":" + rest[0]
                stripped = keyns + ":" + ".".join(rest[:-1]) if len(rest) > 1 else None
                if len(rest) > 1 and full in known_ids:
                    id_, sub = full, False
                elif short in known_ids:
                    id_, sub = short, len(rest) > 1
                elif stripped and stripped in known_ids:
                    id_, sub = stripped, True
                else:
                    st["unmatched"] += 1
                    continue
                if sub:
                    st["subkey_dropped"] += 1
                    continue
                if id_ in res.zh:
                    st["conflict"] += 1
                    continue
                res.zh[id_] = v
    st["mapped_ids"] = len(res.zh)
    return res


def load(version: str, data_dir: str, known_ids: set, allow_download: bool = True, log=None) -> CfpaResult:
    """取包 + 解析一步到位；取不到包时返回空结果并记告警。"""
    log = log or (lambda msg: None)
    res = CfpaResult()
    zip_path, info = fetch_zip(version, data_dir, allow_download, log)
    if not zip_path:
        if allow_download:
            res.warnings.append("未获取到 CFPA 汉化包（版本 %s）" % (version or "未知"))
        else:
            log("未启用 CFPA 自动下载且数据目录里没有 zip，跳过 CFPA 合并")
        return res
    res.info = info
    parsed = parse_zip(zip_path, known_ids)
    parsed.info = info
    return parsed
