#!/usr/bin/env bash
# 隔离真机验证（两步式）：
#   prep : 复制到 /home/guigui/mc/CTI-verify-run（排除 world/backups/logs/runtime_dump），
#          改端口 21335/25576、用超平坦独立世界、部署新脚本
#   run  : 启动副本 → 等 RCON → 跑 /mc_kb_dump 主路径 → 停服 → 删除副本
# 原始运行实例全程只读；I/O 用 ionice 空闲优先级 + nice。
set -uo pipefail

SRC=/home/guigui/mc/CTI0.46
DST=/home/guigui/mc/CTI-verify-run
PLUGIN=/home/guigui/code/AstrBot/data/plugins/astrbot_plugin_mc_manager
VENV=/home/guigui/code/AstrBot/.venv/bin/python
DATA=/tmp/verify_kb_data
MODE="${1:-run}"
SRV_PID=""

log() { printf '\n===== %s =====\n' "$*"; }

prep() {
  log "0) 复制服务器（不拷 world/backups/logs/runtime_dump）"
  rm -rf "${DST}"; mkdir -p "${DST}"
  ionice -c3 nice -n 10 rsync -a \
    --exclude 'world/' --exclude 'world_nether/' --exclude 'world_the_end/' \
    --exclude 'backups/' --exclude 'logs/' --exclude 'crash-reports/' \
    --exclude 'runtime_dump/' --exclude '*.lock' \
    "${SRC}"/ "${DST}"/
  du -sh "${DST}"

  log "1) 改端口 + 超平坦独立世界 + 部署新脚本 + 降内存"
  python3 - "${DST}/server.properties" <<'PY'
import sys
path = sys.argv[1]
out = []
for line in open(path, encoding="utf-8").read().splitlines():
    if line.startswith("server-port="):
        line = "server-port=21335"
    elif line.startswith("rcon.port="):
        line = "rcon.port=25576"
    elif line.startswith("query.port="):
        line = "query.port=21335"
    elif line.startswith("motd="):
        line = "motd=CTI-VERIFY-COPY"
    elif line.startswith("max-players="):
        line = "max-players=2"
    elif line.startswith("level-name="):
        line = "level-name=verifyworld"
    elif line.startswith("level-type="):
        line = "level-type=minecraft\\:flat"
    elif line.startswith("level-seed="):
        line = "level-seed=1"
    elif line.startswith("generate-structures="):
        line = "generate-structures=false"
    elif line.startswith("difficulty="):
        line = "difficulty=peaceful"
    out.append(line)
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
  cp "${PLUGIN}/assets/runtime_dump.js" "${DST}/kubejs/server_scripts/runtime_dump.js"
  sed -i 's/^-Xmx16G -Xms16G$/-Xmx10G -Xms4G/' "${DST}/user_jvm_args.txt"
  mkdir -p "${DST}/runtime_dump"
  echo "副本端口: $(grep -E '^(server-port|rcon.port)=' "${DST}/server.properties" | tr '\n' ' ')"
  echo "世界: $(grep -E '^(level-name|level-type)=' "${DST}/server.properties" | tr '\n' ' ')"
  echo "副本新脚本 sha256: $(sha256sum "${DST}/kubejs/server_scripts/runtime_dump.js" | cut -c1-16)"
  echo "原服脚本 sha256: $(sha256sum "${SRC}/kubejs/server_scripts/runtime_dump.js" | cut -c1-16)"
  echo "原服 commands.json 存在: $(test -f "${SRC}/runtime_dump/commands.json" && echo 是 || echo 否)"
}

stop_copy() {
  log "清理：停止副本并删除目录"
  if [ -n "${SRV_PID}" ] && kill -0 "${SRV_PID}" 2>/dev/null; then
    "${VENV}" - <<'PY' 2>/dev/null || true
import asyncio, sys
sys.path.insert(0, "/home/guigui/code/AstrBot/data/plugins/astrbot_plugin_mc_manager")
from rcon_client import MinecraftRCON
async def main():
    client = MinecraftRCON("127.0.0.1", 25576, "guigui")
    try:
        print("stop ->", await client.execute_async("stop", timeout=20))
    finally:
        await client.close()
asyncio.run(main())
PY
    for _ in $(seq 1 60); do
      kill -0 "${SRV_PID}" 2>/dev/null || break
      sleep 2
    done
    kill -9 "${SRV_PID}" 2>/dev/null || true
  fi
  rm -rf "${DST}" "${DATA}"
  ls -d "${DST}" 2>/dev/null || echo "确认：副本目录已删除"
}

run() {
  trap stop_copy EXIT INT TERM
  log "2) 启动副本服务器"
  cd "${DST}"
  nohup sh run.sh nogui > "${DST}/boot.log" 2>&1 &
  SRV_PID=$!
  echo "副本 PID: ${SRV_PID}"

  log "3) 等待 RCON 就绪（最多 300s，每 30s 打印一次 boot 进度）"
  "${VENV}" - "${DST}" <<'PY'
import asyncio, subprocess, sys, time
from aiomcrcon import Client

dst = sys.argv[1]
async def main():
    deadline = time.time() + 300
    last = 0.0
    while time.time() < deadline:
        try:
            async with Client("127.0.0.1", 25576, "guigui") as c:
                resp = await c.send_cmd("list")
                print("RCON 就绪:", resp[0][:120])
                return
        except Exception:
            now = time.time()
            if now - last > 30:
                last = now
                try:
                    tail = subprocess.run(["tail", "-n", "2", f"{dst}/logs/latest.log"],
                                          capture_output=True, text=True).stdout.strip()
                except Exception:
                    tail = ""
                print(f"...等待中（剩余 {int(deadline - now)}s）{tail[-160:]}")
            await asyncio.sleep(3)
    print("RCON 未能就绪，输出启动日志：")
    print(subprocess.run(["tail", "-n", "60", f"{dst}/boot.log"],
                         capture_output=True, text=True).stdout[-4000:])
    raise SystemExit("RCON 300s 内未就绪")
asyncio.run(main())
PY
  echo "boot: $(grep -o 'Done ([0-9.]*s)' "${DST}/logs/latest.log" 2>/dev/null | tail -1)"

  log "4) 跑 /mc_kb_dump 主路径（隔离数据目录）"
  "${VENV}" "${PLUGIN}/.trellis/tasks/10-25-kubejs-command-dump/verify_live.py" \
    --server-dir "${DST}" --data-dir "${DATA}" \
    --rcon-host 127.0.0.1 --rcon-port 25576 --rcon-password guigui 2>&1 | tail -90
  echo "副本 commands.json: $(stat -c %s "${DST}/runtime_dump/commands.json" 2>/dev/null || echo 缺失) bytes"
}

case "${MODE}" in
  prep) prep ;;
  run) run ;;
  *) echo "用法: $0 prep|run"; exit 2 ;;
esac
