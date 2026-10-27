"""AC4 证据脚本（不属于插件运行时）：用隔离副本走生产 /mc_kb_dump 链路生成真实 commands.json。

用法: python ac4_dump.py <copy_dir> <data_dir> <rcon_port>
"""
import asyncio
import os
import sys

PLUGIN_DIR = "/home/guigui/code/AstrBot/data/plugins/astrbot_plugin_mc_manager"
sys.path.insert(0, PLUGIN_DIR)

import runtime_dump  # noqa: E402
from kb import commands  # noqa: E402
from rcon_client import MinecraftRCON  # noqa: E402


async def main() -> int:
    copy_dir, data_dir, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
    os.makedirs(os.path.join(data_dir, "runtime_dump"), exist_ok=True)
    rcon = MinecraftRCON(host="127.0.0.1", port=port, password="guigui")
    runner = runtime_dump.RuntimeDumpRunner(copy_dir, rcon)

    def rebuild() -> str:
        info = commands.import_snapshot(copy_dir, data_dir)
        return "命令快照导入：status=%s count=%s roots=%s producer=%s %s" % (
            info["status"], info["count"], info["roots"], info["producer"], info["warning"])

    try:
        text = await runner.run(rebuild)
        print(text)
    finally:
        await rcon.close()

    path = commands.snapshot_path(data_dir)
    print("published:", path, "exists:", os.path.isfile(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))