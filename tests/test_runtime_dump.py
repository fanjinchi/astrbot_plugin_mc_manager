"""runtime dump 回执与物品 dump 目录忽略命令快照的离线回归。"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import runtime_dump  # noqa: E402
from kb import builder  # noqa: E402


class FormatCountsTest(unittest.TestCase):
    def test_commands_are_reported_separately_from_item_total(self):
        text = runtime_dump._format_counts(
            {
                "counts": {
                    "item": 16043,
                    "block": 987,
                    "entity": 132,
                    "fluid": 24,
                    "commands": 812,
                },
                "duration_ms": 1446,
            }
        )
        self.assertIn("共 17186 条", text)
        self.assertIn("命令 812 条", text)
        self.assertIn("1.4s", text)

    def test_missing_item_kinds_do_not_break_formatting(self):
        text = runtime_dump._format_counts(
            {"counts": {"commands": 12}, "duration_ms": 230}
        )
        self.assertIn("无物品类别", text)
        self.assertIn("命令 12 条", text)
        self.assertIn("230ms", text)

    def test_parse_dump_summary_carries_commands_count(self):
        response = '[rd] DONE {"version":"3","duration_ms":900,"counts":{"item":5,"commands":2},"failed":[]}'
        summary = runtime_dump._parse_dump_summary(response)
        self.assertEqual(summary["counts"]["commands"], 2)


class LoadRuntimeDumpsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.server = os.path.join(self.tmp, "server")
        self.data = os.path.join(self.tmp, "data")
        self.dump_dir = os.path.join(self.server, "runtime_dump")
        os.makedirs(self.dump_dir)

    def _write(self, name, payload):
        with open(os.path.join(self.dump_dir, name), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def test_commands_snapshot_is_not_counted_as_item_dump(self):
        self._write(
            "commands.json",
            {
                "kind": "commands",
                "schema_version": 1,
                "producer": "kubejs",
                "count": 1,
                "entries": [{"name": "wine", "syntax": "wine info"}],
            },
        )
        rows, warnings = {}, []
        info = builder._load_runtime_dumps(self.server, self.data, rows, warnings)
        self.assertEqual(info["files"], 0)
        self.assertEqual(rows, {})
        self.assertEqual(warnings, [])

    def test_zero_byte_commands_file_does_not_warn(self):
        open(os.path.join(self.dump_dir, "commands.json"), "w").close()
        rows, warnings = {}, []
        info = builder._load_runtime_dumps(self.server, self.data, rows, warnings)
        self.assertEqual(info["files"], 0)
        self.assertEqual(warnings, [])

    def test_item_dump_still_loads_next_to_commands(self):
        self._write(
            "commands.json",
            {
                "kind": "commands",
                "schema_version": 1,
                "producer": "kubejs",
                "count": 1,
                "entries": [{"name": "wine", "syntax": "wine info"}],
            },
        )
        self._write(
            "item.json",
            {
                "kind": "item",
                "count": 1,
                "entries": [
                    {
                        "kind": "item",
                        "id": "ResourceKey[minecraft:item / minecraft:stone]",
                        "tkey": "",
                        "resolved": "石头",
                    }
                ],
            },
        )
        rows, warnings = {}, []
        info = builder._load_runtime_dumps(self.server, self.data, rows, warnings)
        self.assertEqual(info["files"], 1)
        self.assertIn("minecraft:stone", rows)
        self.assertNotIn("wine", rows)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
