#!/usr/bin/env python3
"""把服务器日志里的 ##RD## 行导出成 runtime_dump/*.jsonl。

配合 assets/runtime_dump.js 使用：进服执行 /researchdump 后，脚本会把注册表条目以
"##RD##{...}" 的形式写进 logs/latest.log，本脚本再把它拆成
item/block/entity/fluid 四个 jsonl，供 /mc_kb_rebuild 合并。

用法:
    python3 assets/extract_runtime_dump.py <服务器日志路径> [输出目录]
    # 输出目录默认 = <日志所在目录的上级>/runtime_dump，即 <mc_server_dir>/runtime_dump
    # 例: python3 assets/extract_runtime_dump.py /home/mc/server/logs/latest.log

纯标准库；只读日志、只写 runtime_dump/。
"""

import json
import os
import sys

_KINDS = ("item", "block", "entity", "fluid")


def extract(log_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    buckets = {k: [] for k in _KINDS}
    total = bad = 0
    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            pos = line.find("##RD##")
            if pos < 0:
                continue
            total += 1
            try:
                obj = json.loads(line[pos + 6:].strip())
            except Exception:
                bad += 1
                continue
            kind = obj.get("kind")
            if kind in buckets:
                buckets[kind].append(obj)
            else:
                bad += 1
    counts = {}
    for kind, rows in buckets.items():
        path = os.path.join(out_dir, kind + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        counts[kind] = len(rows)
    return counts, total, bad


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    log_path = argv[1]
    if not os.path.isfile(log_path):
        print("找不到日志文件：%s" % log_path)
        return 1
    out_dir = argv[2] if len(argv) > 2 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(log_path))), "runtime_dump")
    counts, total, bad = extract(log_path, out_dir)
    print("扫描 ##RD## 行：%d 条（无法解析 %d）" % (total, bad))
    if total == 0:
        print("⚠️ 日志里没有 ##RD## 行。请先在游戏内执行 /researchdump 再运行本脚本（空文件会被重建流程忽略）")
    for kind in _KINDS:
        print("  %-6s %d -> %s" % (kind, counts[kind], os.path.join(out_dir, kind + ".jsonl")))
    print("完成：%s" % out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
