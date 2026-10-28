#!/usr/bin/env bash
# P0 隔离副本创建脚本（RCON help fallback 任务）
# 只操作 /home/guigui/mc/rcon-help-probe/，绝不写原实例。
set -euo pipefail

SRC_CTI=/home/guigui/mc/CTI0.46
SRC_FARM=/home/guigui/mc/Farming
ROOT=/home/guigui/mc/rcon-help-probe

echo "== guard: target must not exist =="
if [ -e "$ROOT" ]; then echo "ABORT: $ROOT already exists"; exit 1; fi
install -d "$ROOT"

echo "== record original state (read-only) =="
sha256sum "$SRC_CTI/server.properties" "$SRC_FARM/server.properties"
stat -c '%n mtime=%y size=%s' "$SRC_CTI/server.properties" "$SRC_FARM/server.properties"

copy() {
  echo "== rsync $1 -> $2 =="
  ionice -c3 nice -n 10 rsync -a \
    --exclude 'world/' --exclude 'world_nether/' --exclude 'world_the_end/' \
    --exclude 'backups/' --exclude 'logs/' --exclude 'crash-reports/' \
    --exclude 'runtime_dump/' --exclude 'modernfix/' --exclude '*.lock' \
    --exclude 'session.lock' --exclude 'streamsreflowing-stall-*.txt' \
    --exclude 'installer.log' \
    "$1/" "$2/"
}

copy "$SRC_CTI"  "$ROOT/CTI-kubejs"
copy "$SRC_CTI"  "$ROOT/CTI-nokubejs"
copy "$SRC_FARM" "$ROOT/Farming-kubejs"
copy "$SRC_FARM" "$ROOT/Farming-nokubejs"

echo "== exclude check (must be empty) =="
for d in "$ROOT"/*/; do
  for x in world backups logs crash-reports runtime_dump modernfix; do
    if [ -e "$d$x" ]; then echo "VIOLATION: $d$x exists"; fi
  done
done
echo "(exclude check done)"

echo "== configure ports / level / memory =="
python3 - "$ROOT" <<'PY'
import io, os, sys
root = sys.argv[1]
plan = {
    "CTI-kubejs":       (21340, 25580, "-Xmx10G -Xms4G"),
    "CTI-nokubejs":     (21341, 25581, "-Xmx10G -Xms4G"),
    "Farming-kubejs":   (21342, 25582, "-Xmx8G -Xms2G"),
    "Farming-nokubejs": (21343, 25583, "-Xmx8G -Xms2G"),
}
for name, (port, rport, heap) in plan.items():
    d = os.path.join(root, name)
    p = os.path.join(d, "server.properties")
    lines = io.open(p, encoding="utf-8").read().splitlines()
    wanted = {
        "server-port": str(port), "rcon.port": str(rport), "query.port": str(port),
        "server-ip": "127.0.0.1", "level-name": "probe_world",
        "motd": "PROBE " + name, "enable-query": "false",
    }
    out, seen = [], set()
    for line in lines:
        if "=" in line and not line.startswith("#"):
            k = line.split("=", 1)[0]
            if k in wanted:
                seen.add(k); out.append(k + "=" + wanted[k]); continue
        out.append(line)
    for k, v in wanted.items():
        if k not in seen:
            out.append(k + "=" + v)
    io.open(p, "w", encoding="utf-8").write("\n".join(out) + "\n")
    props = dict(l.split("=", 1) for l in io.open(p, encoding="utf-8").read().splitlines()
                 if "=" in l and not l.startswith("#"))
    assert props["server-port"] == str(port), (name, props.get("server-port"))
    assert props["rcon.port"] == str(rport), (name, props.get("rcon.port"))
    assert props["level-name"] == "probe_world" and props["server-ip"] == "127.0.0.1"
    assert props["enable-rcon"] == "true"
    io.open(os.path.join(d, "user_jvm_args.txt"), "w", encoding="utf-8").write(heap + "\n")
    print("configured", name, "game", port, "rcon", rport, "heap", heap)
PY

echo "== disable KubeJS in no-kubejs copies =="
disable_kubejs() {
  local d="$1"; shift
  install -d "$d/probe-disabled-mods"
  for j in "$@"; do
    if [ -f "$d/mods/$j" ]; then mv -v "$d/mods/$j" "$d/probe-disabled-mods/";
    else echo "WARN: missing jar $j in $d"; fi
  done
  if [ -d "$d/kubejs" ]; then mv -v "$d/kubejs" "$d/probe-disabled-mods/kubejs-scripts"; fi
  rm -f "$d/rhino.local.properties"
}
disable_kubejs "$ROOT/CTI-nokubejs" \
  kubejs-forge-1902.6.2-build.73.jar rhino-forge-1902.2.3-build.284.jar \
  kubejs_botania-1.3.1-forge.jar kubejs-create-forge-1902.2.4-build.36.jar \
  kubejsdelight-1.19.2-1.1.2.jar kubejs-immersive-engineering-1902.2.3-build.18.jar \
  kubejs-mekanism-1902.1.5-build.20.jar kubejspowah-1.2.jar \
  kubejs-thermal-1902.1.9-build.16.jar
disable_kubejs "$ROOT/Farming-nokubejs" \
  kubejsadditions-forge-4.3.4.jar kubejs-forge-2001.6.5-build.16.jar \
  '[kubejs]lootjs-forge-1.20.1-2.13.1.jar' 'rhino-forge-2001.2.3-build.10.jar' \
  '[农场物语-魔法木桶]magic_barrel-1.0.17-kubejs.jar'

echo "== leftover kubejs jars in no-kubejs copies (must be empty) =="
ls "$ROOT/CTI-nokubejs/mods" | grep -i -E 'kube|rhino' || echo "(cti: none)"
ls "$ROOT/Farming-nokubejs/mods" | grep -i -E 'kube|rhino' || echo "(farm: none)"

echo "== sizes =="
du -sh "$ROOT"/*
echo "== original hashes after copy (must equal before) =="
sha256sum "$SRC_CTI/server.properties" "$SRC_FARM/server.properties"

cat > "$ROOT/MANIFEST.md" <<EOF
# P0 隔离副本清单（$(date -Iseconds)）

源实例（只读复制，未修改）：`$SRC_CTI`（1.19.2 Forge 43.4.12）、`$SRC_FARM`（1.20.1 Forge 47.4.20）

| 副本 | 源 | server-port | rcon.port | heap | KubeJS |
|---|---|---|---|---|---|
| CTI-kubejs | CTI0.46 | 21340 | 25580 | -Xmx10G -Xms4G | 保留 |
| CTI-nokubejs | CTI0.46 | 21341 | 25581 | -Xmx10G -Xms4G | 移入 probe-disabled-mods/ |
| Farming-kubejs | Farming | 21342 | 25582 | -Xmx8G -Xms2G | 保留 |
| Farming-nokubejs | Farming | 21343 | 25583 | -Xmx8G -Xms2G | 移入 probe-disabled-mods/ |

- 排除内容：world*/、backups/、logs/、crash-reports/、runtime_dump/、modernfix/、*.lock、Farming 的 stall 日志与 installer.log。
- 所有副本：server-ip=127.0.0.1、level-name=probe_world（新世界）、enable-query=false、motd 标记 PROBE。
- 回滚：整体删除 `$ROOT` 即可；原实例未写入。
EOF
echo "== done =="
