"""KubeJS 脚本的离线契约测试：用 Node 桩执行 assets/runtime_dump.js。

覆盖「dispatcher → commands.json → Python 契约/查询」整条主路径，不需要启动 Minecraft。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import runtime_dump  # noqa: E402
from kb import commands  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_HARNESS = os.path.join(_HERE, "js_dump_harness.js")


@unittest.skipIf(shutil.which("node") is None, "需要 node 才能执行 KubeJS 脚本桩")
class DumpScriptContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        output = subprocess.run(
            ["node", _HARNESS], capture_output=True, text=True, check=True
        ).stdout
        cls.result = json.loads(output)

    def _commands_write(self, run):
        found = [w for w in run["writes"] if w["path"] == "runtime_dump/commands.json"]
        return found[0]["payload"] if found else None

    def test_writes_all_kinds_and_rd_version_3(self):
        run = self.result["ok"]
        self.assertEqual(
            [w["path"] for w in run["writes"]],
            [
                "runtime_dump/item.json",
                "runtime_dump/block.json",
                "runtime_dump/entity.json",
                "runtime_dump/fluid.json",
                "runtime_dump/commands.json",
            ],
        )
        summary = runtime_dump._parse_dump_summary(run["messages"][0])
        self.assertIsNotNone(summary)
        self.assertEqual(summary["version"], "3")
        self.assertEqual(summary["counts"]["commands"], 5)
        self.assertEqual(summary["failed"], [])
        self.assertEqual(summary["counts"]["item"], 2)

    def test_commands_payload_matches_shared_contract(self):
        payload = self._commands_write(self.result["ok"])
        self.assertEqual(payload["kind"], "commands")
        self.assertEqual(payload["producer"], "kubejs")
        self.assertEqual(payload["count"], len(payload["entries"]))
        snapshot, reason = commands.validate_snapshot(payload)
        self.assertEqual(reason, "")
        self.assertEqual(
            [entry["syntax"] for entry in snapshot["entries"]],
            ["alias", "foo", "foo <count>", "foo bar", "loop"],
        )
        by_syntax = {entry["syntax"]: entry for entry in snapshot["entries"]}
        self.assertEqual(by_syntax["alias"]["redirect"], "foo")
        self.assertEqual(by_syntax["loop"]["redirect"], "...")
        self.assertNotIn("redirect", by_syntax["foo bar"])
        self.assertEqual(by_syntax["foo"]["level"], None)

    def test_usage_paths_reach_search(self):
        payload = self._commands_write(self.result["ok"])
        snapshot, _ = commands.validate_snapshot(payload)
        data_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(data_dir, ignore_errors=True))
        self.assertTrue(commands.publish_snapshot(snapshot, data_dir)[0])

        text = commands.search_commands("foo", data_dir=data_dir)
        self.assertIn("· foo", text)
        self.assertIn("· foo bar", text)
        self.assertIn("· foo <count>", text)
        self.assertIn("已注册的路径", text)

        text = commands.search_commands("alias", data_dir=data_dir)
        self.assertIn("重定向：alias -> foo", text)

    def test_external_root_redirect_is_marked_not_executable(self):
        payload = self._commands_write(self.result["externalRoot"])
        snapshot, reason = commands.validate_snapshot(payload)
        self.assertEqual(reason, "")
        by_name = {entry["name"]: entry for entry in snapshot["entries"]}
        self.assertEqual(by_name["execute"]["syntax"], "execute")
        self.assertEqual(by_name["execute"]["redirect"], "...")

        data_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(data_dir, ignore_errors=True))
        self.assertTrue(commands.publish_snapshot(snapshot, data_dir)[0])
        text = commands.search_commands("execute", data_dir=data_dir)
        self.assertIn("重定向：execute ...", text)
        self.assertNotIn("· execute ->", text)

    def test_command_failure_is_isolated_from_item_dumps(self):
        run = self.result["broken"]
        self.assertIsNone(self._commands_write(run))
        self.assertIn("runtime_dump/item.json", [w["path"] for w in run["writes"]])
        summary = runtime_dump._parse_dump_summary(run["messages"][0])
        self.assertEqual(summary["failed"], ["commands"])
        self.assertNotIn("commands", summary["counts"])


if __name__ == "__main__":
    unittest.main()
