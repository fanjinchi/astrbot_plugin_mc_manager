#!/usr/bin/env python3
"""P0 环境手术：no-KubeJS 副本的 jar 依赖清理（仅隔离副本，原实例不动）。

两类操作，均先备份到 probe-disabled-mods/：
  1) --drop-nested <path>[,<path>]  从宿主 jar 中删除 jar-in-jar 条目并同步 metadata.json
  2) --strip-kubejs-refs           递归删除 worldgen JSON 中形如 "kubejs:*" 的列表元素
"""
import argparse
import hashlib
import json
import os
import shutil
import zipfile


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def backup(path, backup_dir, tag):
    os.makedirs(backup_dir, exist_ok=True)
    dst = os.path.join(backup_dir, f"{os.path.basename(path)}.{tag}")
    if not os.path.exists(dst):
        shutil.copy2(path, dst)
    return dst


def repack(jar_path, transform):
    tmp = jar_path + ".tmp"
    with zipfile.ZipFile(jar_path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            new = transform(item.filename, data)
            if new is None:
                continue
            zout.writestr(item, new)
    os.replace(tmp, jar_path)


def strip_refs_in_json(data):
    """递归删除列表里以 kubejs: 开头的字符串元素。"""
    changed = [False]

    def walk(node):
        if isinstance(node, list):
            out = []
            for v in node:
                if isinstance(v, str) and v.startswith("kubejs:"):
                    changed[0] = True
                    continue
                out.append(walk(v))
            return out
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return node

    return walk(data), changed[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", required=True)
    ap.add_argument("--drop-nested", default="")
    ap.add_argument("--strip-kubejs-refs", action="store_true")
    args = ap.parse_args()

    copy = args.copy.rstrip("/")
    backup_dir = os.path.join(copy, "probe-disabled-mods")
    report = {"copy": os.path.basename(copy), "actions": []}

    for jar_name in args.drop_nested.split(","):
        jar_name = jar_name.strip()
        if not jar_name:
            continue
        jar = os.path.join(copy, "mods", jar_name)
        if not os.path.exists(jar):
            report["actions"].append({"jar": jar_name, "skipped": "missing"})
            continue
        nested = [n for n in zipfile.ZipFile(jar).namelist()
                  if n.startswith("META-INF/jarjar/") and n.endswith(".jar")]
        # 由调用方给出要删的内嵌条目全名
        report["actions"].append({"jar": jar_name, "nested_before": len(nested)})

    drop = set()
    jar_name = None
    for token in args.drop_nested.split(","):
        token = token.strip()
        if not token:
            continue
        if "::" in token:
            jar_name, entry = token.split("::", 1)
            drop.add((jar_name, entry))
        else:
            jar_name = token
    by_jar = {}
    for j, e in drop:
        by_jar.setdefault(j, set()).add(e)

    for jname, entries in by_jar.items():
        jar = os.path.join(copy, "mods", jname)
        before = sha256(jar)
        bpath = backup(jar, backup_dir, "original")

        def transform(name, data, entries=entries):
            if name in entries:
                return None
            if name == "META-INF/jarjar/metadata.json":
                meta = json.loads(data.decode("utf-8"))
                meta["jars"] = [j for j in meta.get("jars", []) if j.get("path") not in entries]
                return json.dumps(meta, indent=2).encode("utf-8")
            return data

        repack(jar, transform)
        report["actions"].append({
            "jar": jname, "dropped": sorted(entries),
            "sha256_before": before, "sha256_after": sha256(jar), "backup": bpath,
        })

    if args.strip_kubejs_refs:
        for jar in sorted(os.listdir(os.path.join(copy, "mods"))):
            path = os.path.join(copy, "mods", jar)
            if not jar.endswith(".jar") or not os.path.isfile(path):
                continue
            touched = []
            with zipfile.ZipFile(path) as zin:
                for n in zin.namelist():
                    if not n.lower().endswith(".json") or "/worldgen/" not in n:
                        continue
                    try:
                        data = json.loads(zin.read(n))
                    except Exception:
                        continue
                    new, changed = strip_refs_in_json(data)
                    if changed:
                        touched.append(n)
            if not touched:
                continue
            before = sha256(path)
            bpath = backup(path, backup_dir, "kubejsrefs")
            payload = {}

            def transform(name, data, touched=set(touched), payload=payload):
                if name in touched:
                    obj = json.loads(data)
                    new, _ = strip_refs_in_json(obj)
                    payload[name] = True
                    return json.dumps(new, indent=2).encode("utf-8")
                return data

            repack(path, transform)
            report["actions"].append({
                "jar": jar, "stripped_json": sorted(touched),
                "sha256_before": before, "sha256_after": sha256(path), "backup": bpath,
            })

    out = os.path.join(backup_dir, "surgery-report.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2)[:4000])
    print("report:", out)


if __name__ == "__main__":
    main()
