#!/usr/bin/env bash
# Farming（1.20.1）原服直接验证：临时改端口 + 部署新脚本 → 用 Java 21 启动 → /mc_kb_dump → 停服 → 还原。
# Farming 已停用，用户确认可直接在原服务器目录测试。
set -uo pipefail

SRV=/home/guigui/mc/Farming
PLUGIN=/home/guigui/code/AstrBot/data/plugins/astrbot_plugin_mc_manager
VENV=/home/guigui/code/AstrBot/.venv/bin/python
JAVA21=/usr/lib/jvm/java-21-openjdk-amd64
DATA=/tmp/verify_farming_data
SRV_PID=""
SCRIPT_DEPLOYED=""
PROPS_BAK=""

log() { printf '\n===== %s =====\n' "$*"; }

restore() {
  log "还原 Farming 配置与测试痕迹"
  if [ -n "${PROPS_BAK}" ] && [ -f "${PROPS_BAK}" ]; then
    mv -f "${PROPS_BAK}" "${SRV}/server.properties"
    echo "server.properties 已还原"
  fi
  if [ -n "${SCRIPT_DEPLOYED}" ] && [ -f "${SCRIPT_DEPLOYED}" ]; then
    rm -f "${SCRIPT_DEPLOYED}"
    echo "已移除部署的 runtime_dump.js（原目录本来没有）"
  fi
  rm -rf "${SRV}/runtime_dump" "${DATA}"
  rm -f "${SRV}/boot.verify.log"
  rm -f "${SRV}"/crash-reports/crash-2026-10-26_*.fml.txt
  echo "已移除 runtime_dump/、临时数据目录、本次 boot 日志与崩溃报告"
  echo "端口还原: $(grep -E '^(server-port|rcon.port)=' "${SRV}/server.properties" | tr '\n' ' ')"
  ls "${SRV}/kubejs/server_scripts/runtime_dump.js" 2>/dev/null || echo "确认：runtime_dump.js 不在原目录"
}

stop_server() {
  if [ -n "${SRV_PID}" ] && kill -0 "${SRV_PID}" 2>/dev/null; then
    log "停止 Farming 服务器"
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
    for _ in $(seq 1 90); do
      kill -0 "${SRV_PID}" 2>/dev/null || break
      sleep 2
    done
    kill -9 "${SRV_PID}" 2>/dev/null || true
  fi
}

cleanup() { stop_server; restore; }
trap cleanup EXIT INT TERM

log "0) 备份配置 + 改端口 + 部署新脚本"
PROPS_BAK="${SRV}/server.properties.verify-bak"
cp "${SRV}/server.properties" "${PROPS_BAK}"
python3 - "${SRV}/server.properties" <<'PY'
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
        line = "motd=FARMING-VERIFY"
    elif line.startswith("max-players="):
        line = "max-players=2"
    out.append(line)
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
mkdir -p "${SRV}/kubejs/server_scripts" "${SRV}/runtime_dump"
cp "${PLUGIN}/assets/runtime_dump.js" "${SRV}/kubejs/server_scripts/runtime_dump.js"
SCRIPT_DEPLOYED="${SRV}/kubejs/server_scripts/runtime_dump.js"
echo "端口: $(grep -E '^(server-port|rcon.port)=' "${SRV}/server.properties" | tr '\n' ' ')"
echo "新脚本 sha256: $(sha256sum "${SCRIPT_DEPLOYED}" | cut -c1-16)"
echo "Java: $("${JAVA21}/bin/java" -version 2>&1 | head -1)"

log "1) 启动 Farming 服务器（Java 21 / 1.20.1 / 279 mods）"
cd "${SRV}"
PATH="${JAVA21}/bin:${PATH}" nohup sh run.sh nogui > "${SRV}/boot.verify.log" 2>&1 &
SRV_PID=$!
echo "PID: ${SRV_PID}"

log "2) 等待 RCON 就绪（最多 360s，每 40s 打印进度）"
"${VENV}" - "${SRV}" <<'PY'
import asyncio, subprocess, sys, time
from aiomcrcon import Client

srv = sys.argv[1]
async def main():
    deadline = time.time() + 360
    last = 0.0
    while time.time() < deadline:
        try:
            async with Client("127.0.0.1", 25576, "guigui") as c:
                resp = await c.send_cmd("list")
                print("RCON 就绪:", resp[0][:120])
                return
        except Exception:
            now = time.time()
            if now - last > 40:
                last = now
                tail = subprocess.run(["tail", "-n", "2", f"{srv}/logs/latest.log"],
                                      capture_output=True, text=True).stdout.strip()
                print(f"...等待中（剩余 {int(deadline-now)}s）{tail[-150:]}")
            await asyncio.sleep(3)
    print(subprocess.run(["tail", "-n", "60", f"{srv}/boot.verify.log"],
                         capture_output=True, text=True).stdout[-3000:])
    raise SystemExit("RCON 360s 内未就绪")
asyncio.run(main())
PY
echo "boot: $(grep -oE 'Done \([0-9.]+s\)!' "${SRV}/logs/latest.log" 2>/dev/null | tail -1)"

log "3) 跑 /mc_kb_dump 主路径（关键词含 wine）"
"${VENV}" "${PLUGIN}/.trellis/tasks/10-25-kubejs-command-dump/verify_live.py" \
  --server-dir "${SRV}" --data-dir "${DATA}" \
  --rcon-host 127.0.0.1 --rcon-port 25576 --rcon-password guigui \
  --keywords "wine,wine info,age,researchdump,weather" 2>&1 | tail -100
echo "commands.json: $(stat -c %s "${SRV}/runtime_dump/commands.json" 2>/dev/null || echo 缺失) bytes"
exit 0
