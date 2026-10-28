"""父任务阶段 7：最终集成验收（真实产物 + 生产代码，不启服务器）。

证据源：
- KubeJS 快照：/home/guigui/mc/rcon-help-probe/CTI-kubejs/runtime_dump/commands.json
  （2026-10-28 14:37 P6 AC6 期间由 /mc_kb_dump 真实生成，sha256 4ff23bd7…）
- RCON 快照：/tmp/p6-cti-h7no395z/runtime_dump/commands.json
  （2026-10-28 14:33 P6 AC1 期间由 CTI-nokubejs 真实 /mc_kb_rcon_scan 发布，sha256 8b50e867…）
"""
import json
import os
import re
import shutil
import sys
import tempfile

REPO = "/home/guigui/code/AstrBot/data/plugins/astrbot_plugin_mc_manager"
sys.path.insert(0, REPO)

from kb import commands as cmd  # noqa: E402

KJS = "/home/guigui/mc/rcon-help-probe/CTI-kubejs/runtime_dump/commands.json"
RCON = "/tmp/p6-cti-h7no395z/runtime_dump/commands.json"

failures = []


def check(cond, label, extra=""):
    print(("PASS " if cond else "FAIL ") + label + ((" | " + extra) if extra else ""))
    if not cond:
        failures.append(label)


def publish(src, data_dir):
    data = json.load(open(src, encoding="utf-8"))
    snap, reason = cmd.validate_snapshot(data)
    assert snap is not None, reason
    ok, err = cmd.publish_snapshot(snap, data_dir)
    assert ok, err
    return snap


def root_blocks(text):
    return re.findall(r"^- /(\S+)", text, re.M)


kjs_dir = tempfile.mkdtemp(prefix="p7-kjs-")
rcon_dir = tempfile.mkdtemp(prefix="p7-rcon-")
vanilla_dir = tempfile.mkdtemp(prefix="p7-vanilla-")

print("== 1. 同一契约：两份真实快照都通过同一个 validate_snapshot")
kjs_snap = publish(KJS, kjs_dir)
rcon_snap = publish(RCON, rcon_dir)
check(kjs_snap["producer"] == "kubejs" and rcon_snap["producer"] == "rcon", "producer 字段分别为 kubejs / rcon")
check(
    kjs_snap["count"] == len(kjs_snap["entries"]) and rcon_snap["count"] == len(rcon_snap["entries"]),
    "count 与条目数一致",
    f"kjs={kjs_snap['count']} rcon={rcon_snap['count']}",
)

print("\n== 2. 单一消费链：两套快照发布进不同数据目录后走同一个 search_commands")
kjs_q = cmd.search_commands("advancement", 8, data_dir=kjs_dir)
rcon_q = cmd.search_commands("advancement", 8, data_dir=rcon_dir)
check("/advancement" in kjs_q and "/advancement" in rcon_q, "两个生产者都能命中 /advancement")
check(
    "注：运行时语法是服务端当前命令树已注册的路径" in kjs_q,
    "KubeJS 提示：已注册路径不代表必然可执行",
)
check(
    "注：运行时语法来自 RCON help" in rcon_q and "压缩语法" in rcon_q,
    "RCON 提示：深层分支是压缩语法",
)
check(
    root_blocks(kjs_q).count("advancement") == 1 and root_blocks(rcon_q).count("advancement") == 1,
    "同一根只出现一次（无重复占位）",
)

print("\n== 3. 同一查询改进：token AND / 归一化 / 中文 desc 都不分 producer")
for name, d in (("kjs", kjs_dir), ("rcon", rcon_dir)):
    out = cmd.search_commands("封禁", 8, data_dir=d)
    check(
        "/ban — 封禁玩家" in out and "来源未知" in out and "权限未知" in out,
        f"[{name}] 中文 desc 命中运行时同根（只继承内置 desc/cat，来源权限仍未知）",
    )
    check(root_blocks(out).count("ban") == 1, f"[{name}] /ban 只出现一次")
    out2 = cmd.search_commands("advancement grant", 8, data_dir=d)
    check("/advancement" in out2, f"[{name}] 多 token AND 查询可用")
# 归一化等价：channel mode / channel_mode / channel-mode 三种写法命中同一根
if "channel" in {e["name"] for e in kjs_snap["entries"]}:
    outs = [cmd.search_commands(q, 8, data_dir=kjs_dir) for q in ("channel mode", "channel_mode", "channel-mode")]
    check(outs[0] == outs[1] == outs[2], "空白/下划线/连字符归一化等价（同一 producer 内）")

print("\n== 4. 无快照时原版兜底，且不与运行时段重复")
v = cmd.search_commands("ban", 8, data_dir=vanilla_dir)
check("/ban" in v and "原版" in v, "无快照：内置原版 /ban 可搜到")
check("注：运行时语法" not in v, "无快照：不追加运行时提示")
for name, d in (("kjs", kjs_dir), ("rcon", rcon_dir)):
    out = cmd.search_commands("ban", 8, data_dir=d)
    check(root_blocks(out).count("ban") == 1, f"[{name}] 运行时同根合并后不与内置重复")

print("\n== 5. consumer 不感知 producer：同一批 entries 改 producer 只影响提示文案")
kjs_as_rcon = dict(kjs_snap, producer="rcon")
validated, reason = cmd.validate_snapshot(kjs_as_rcon)
check(validated is not None, "同一份 KubeJS 条目被 rcon producer 校验接受（契约无 producer 专属字段）", reason or "")
swap_dir = tempfile.mkdtemp(prefix="p7-swap-")
cmd.publish_snapshot(validated, swap_dir)
a = cmd.search_commands("advancement", 8, data_dir=kjs_dir)
b = cmd.search_commands("advancement", 8, data_dir=swap_dir)
strip_note = lambda text: "\n".join(l for l in text.splitlines() if not l.startswith("注："))
check(strip_note(a) == strip_note(b), "去掉提示行后两条 producer 输出完全一致（匹配/排序逻辑不分叉）")

print("\n== 6. 无效快照仍被同一入口拒绝（失败关闭不会被绕过）")
bad_producer = dict(kjs_snap, producer="kubejs2")
bad_count = dict(kjs_snap, count=kjs_snap["count"] + 1)
bad_entry = json.loads(json.dumps(kjs_snap))
bad_entry["entries"][0]["syntax"] = "not-" + bad_entry["entries"][0]["name"]
for label, payload in (("producer 非法", bad_producer), ("count 不一致", bad_count), ("name/syntax 不一致", bad_entry)):
    got, why = cmd.validate_snapshot(payload)
    check(got is None and bool(why), f"拒绝 {label}", why)

print("\n== 7. 跨机只复制 commands.json 即可查询（同一 schema，无 producer 专属依赖）")
copy_dir = tempfile.mkdtemp(prefix="p7-copy-")
os.makedirs(os.path.join(copy_dir, cmd.SNAPSHOT_DIR), exist_ok=True)
shutil.copyfile(os.path.join(rcon_dir, cmd.SNAPSHOT_DIR, cmd.SNAPSHOT_NAME), os.path.join(copy_dir, cmd.SNAPSHOT_DIR, cmd.SNAPSHOT_NAME))
out = cmd.search_commands("advancement", 8, data_dir=copy_dir)
check("/advancement" in out and "注：运行时语法来自 RCON help" in out, "跨机复制 RCON commands.json 后查询可用且 producer 保持")

print("\n== 8. 两版本真实产物（Farming 1.20.1）同样通过同一契约与查询入口")
farming_kjs = "/home/guigui/mc/rcon-help-probe/Farming-kubejs/runtime_dump/commands.json"
farming_rcon_dirs = [d for d in os.listdir("/tmp") if d.startswith("p6-ac6-cti-f4bua1fh")]
fk_snap = publish(farming_kjs, tempfile.mkdtemp(prefix="p7-fkjs-"))
check(fk_snap["producer"] == "kubejs" and fk_snap["count"] == 2248, "Farming KubeJS 快照 2248 条校验通过")
fd = tempfile.mkdtemp(prefix="p7-fkjs-q-")
publish(farming_kjs, fd)
wine = cmd.search_commands("wine age", 8, data_dir=fd)
check("/wine" in wine and "wine age" in wine, "Farming KubeJS：wine age 可查询")

print("\n== 9. 文档/spec 声明与代码常量一致（抽查）")
import inspect

src = inspect.getsource(cmd)
check("SNAPSHOT_PRODUCERS = (\"kubejs\", \"rcon\")" in src, "spec 声明的 producer 枚举与代码一致")
readme = open(os.path.join(REPO, "README.md"), encoding="utf-8").read()
spec = open(os.path.join(REPO, ".trellis/spec/backend/runtime-dump.md"), encoding="utf-8").read()
for label, doc in (("README", readme), ("runtime-dump.md", spec)):
    check("2N+4" in doc or "2N + 4" in doc, f"{label} 记录 2N+4 请求预算")
    check("rcon" in doc and "kubejs" in doc, f"{label} 同时说明两条采集路径")
    check("getAllUsage" in doc, f"{label} 说明 KubeJS getAllUsage 主路径")
rcon_help = open(os.path.join(REPO, "rcon_help.py"), encoding="utf-8").read()
check("2 * roots + 4" in rcon_help or "2N+4" in rcon_help or "2 * len(roots)" in rcon_help, "代码实现 2N+4 预算")

print("\n== 结果")
if failures:
    print("FAILURES:", failures)
    sys.exit(1)
print("ALL INTEGRATION CHECKS PASSED")
