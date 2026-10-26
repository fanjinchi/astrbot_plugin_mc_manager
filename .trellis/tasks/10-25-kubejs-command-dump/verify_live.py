"""真机验证脚本（不属于插件运行时）：/mc_kb_dump 主路径的命令树导出与查询闭环。

由主会话在获批实例上执行，用于收集 AC1–AC5 的服务器侧证据。用法：

    /home/guigui/code/AstrBot/.venv/bin/python .trellis/tasks/10-25-kubejs-command-dump/verify_live.py \
        --server-dir /home/guigui/mc/CTI0.46 \
        --data-dir /home/guigui/code/AstrBot/data/plugin_data/astrbot_plugin_mc_manager
"""

import argparse
import asyncio
import json
import os
import sys
import time

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, PLUGIN_DIR)

import runtime_dump  # noqa: E402
from kb import KnowledgeBase, commands  # noqa: E402
from rcon_client import MinecraftRCON  # noqa: E402


def section(title):
    print("\n" + "=" * 12, title, "=" * 12)


def read_commands_snapshot(server_dir):
    path = os.path.join(server_dir, "runtime_dump", "commands.json")
    if not os.path.isfile(path):
        return None, "缺失"
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data, "%d bytes" % os.path.getsize(path)


async def main(args):
    kb = KnowledgeBase(
        data_dir=args.data_dir,
        server_dir=args.server_dir,
        mc_version=args.mc_version,
        vanilla_zh_download=False,
        cfpa_auto_download=False,
    )
    rcon = MinecraftRCON(args.rcon_host, args.rcon_port, args.rcon_password)

    section("0) RCON")
    print("list ->", await rcon.execute_async("list", timeout=10))

    section("1) /mc_kb_dump 主路径（部署新脚本 → 按需 /reload → researchdump → 重建）")
    runner = runtime_dump.RuntimeDumpRunner(args.server_dir, rcon)
    started = time.time()
    result = await runner.run(lambda: kb.rebuild(lambda msg: print("   [rebuild]", msg)))
    print("耗时 %.1fs" % (time.time() - started))
    print(result)

    section("2) 命令快照产物")
    data, size = read_commands_snapshot(args.server_dir)
    if data is None:
        print("❌ 未生成 commands.json")
        return 1
    entries = data.get("entries") or []
    roots = sorted({e.get("name") for e in entries})
    redirects = [e for e in entries if e.get("redirect")]
    print("size=%s kind=%s schema=%s producer=%s count=%s roots=%d redirects=%d" % (
        size, data.get("kind"), data.get("schema_version"), data.get("producer"),
        data.get("count"), len(roots), len(redirects)))
    print("样例条目:", json.dumps(entries[:5], ensure_ascii=False))
    print("root 数 >= 100 ?", len(roots) >= 100, "| 含 researchdump ?", "researchdump" in roots)
    print("含 execute ?", "execute" in roots)

    section("3) 物品 dump 未回退")
    for kind in ("item", "block", "entity", "fluid"):
        path = os.path.join(args.server_dir, "runtime_dump", kind + ".json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
            print("%-6s count=%s size=%d" % (kind, payload.get("count"), os.path.getsize(path)))
        else:
            print("%-6s 缺失" % kind)

    section("4) search_mc_commands 查询（数据目录发布快照）")
    published = commands.snapshot_path(args.data_dir)
    print("canonical:", published, os.path.isfile(published))
    for keyword in ("researchdump", "execute", "weather"):
        text = commands.search_commands(keyword, limit=2, data_dir=args.data_dir)
        print("\n--- keyword=%s ---\n%s" % (keyword, text[:900]))

    section("5) 幂等：再次触发 dump，count 与查询不重复")
    again = await rcon.execute_async(runtime_dump.DUMP_COMMAND, timeout=runtime_dump.TRIGGER_TIMEOUT)
    summary = runtime_dump._parse_dump_summary(again)
    print("第二次 DONE:", bool(summary), summary and summary.get("counts"))
    data2, _ = read_commands_snapshot(args.server_dir)
    print("count 一致 ?", data2.get("count") == data.get("count"))
    info = commands.import_snapshot(args.server_dir, args.data_dir)
    print("重新导入:", info)
    text = commands.search_commands("researchdump", limit=3, data_dir=args.data_dir)
    print("root 条目出现次数:", text.count("- /researchdump"))
    await rcon.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-dir", default="/home/guigui/mc/CTI0.46")
    parser.add_argument("--data-dir",
                        default="/home/guigui/code/AstrBot/data/plugin_data/astrbot_plugin_mc_manager")
    parser.add_argument("--mc-version", default="")
    parser.add_argument("--rcon-host", default="127.0.0.1")
    parser.add_argument("--rcon-port", type=int, default=25575)
    parser.add_argument("--rcon-password", default="guigui")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args)))
