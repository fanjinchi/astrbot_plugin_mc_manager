"""命令快照契约的离线回归：校验 / 原子发布 / 导入 / 查询聚合。

标准库 unittest，临时目录隔离；这些用例是派生快照契约的离线证据，不替代真机验证。
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kb import commands  # noqa: E402


def _entry(name, syntax, redirect="", source="unknown", level=None):
    entry = {"name": name, "syntax": syntax, "source": source, "level": level}
    if redirect:
        entry["redirect"] = redirect
    return entry


def _snapshot(entries, producer="kubejs"):
    return {
        "kind": "commands",
        "schema_version": 1,
        "producer": producer,
        "count": len(entries),
        "entries": entries,
    }


class ValidateSnapshotTest(unittest.TestCase):
    def test_normalizes_dedupes_and_sorts(self):
        snapshot, reason = commands.validate_snapshot(
            _snapshot(
                [
                    _entry("wine", "wine age <years>"),
                    _entry("wine", "wine info"),
                    _entry("wine", "wine info"),
                    _entry("alias", "alias", redirect="wine"),
                ]
            )
        )
        self.assertEqual(reason, "")
        self.assertEqual(snapshot["count"], 3)
        self.assertEqual(
            [e["syntax"] for e in snapshot["entries"]],
            ["alias", "wine age <years>", "wine info"],
        )
        self.assertEqual(snapshot["entries"][0]["redirect"], "wine")

    def test_missing_level_is_none_and_bool_level_rejected(self):
        snapshot, reason = commands.validate_snapshot(
            _snapshot(
                [
                    {"name": "foo", "syntax": "foo"},
                    {"name": "bar", "syntax": "bar", "level": True},
                ]
            )
        )
        self.assertEqual(reason, "")
        self.assertEqual([e["level"] for e in snapshot["entries"]], [None, None])

    def test_accepts_rcon_producer(self):
        snapshot, _ = commands.validate_snapshot(
            _snapshot([_entry("foo", "foo")], "rcon")
        )
        self.assertEqual(snapshot["producer"], "rcon")

    def test_rejects_broken_snapshots(self):
        cases = {
            "非对象": [],
            "错误 kind": dict(_snapshot([_entry("foo", "foo")]), kind="items"),
            "错误版本": dict(_snapshot([_entry("foo", "foo")]), schema_version=2),
            "未知 producer": _snapshot([_entry("foo", "foo")], "handmade"),
            "空 entries": _snapshot([]),
            "count 不符": dict(_snapshot([_entry("foo", "foo")]), count=2),
            "条目非对象": _snapshot(["foo"]),
            "缺 name": _snapshot([{"syntax": "foo"}]),
            "缺 syntax": _snapshot([{"name": "foo"}]),
            "name 与 syntax 不一致": _snapshot([_entry("foo", "bar baz")]),
        }
        for label, data in cases.items():
            snapshot, reason = commands.validate_snapshot(data)
            self.assertIsNone(snapshot, label)
            self.assertTrue(reason, label)


class PublishSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True)
        )

    def test_writes_canonical_snapshot(self):
        snapshot, _ = commands.validate_snapshot(_snapshot([_entry("foo", "foo bar")]))
        ok, detail = commands.publish_snapshot(snapshot, self.tmp)
        self.assertTrue(ok, detail)
        with open(commands.snapshot_path(self.tmp), encoding="utf-8") as fh:
            written = json.load(fh)
        self.assertEqual(written["count"], 1)
        self.assertEqual(written["entries"][0]["syntax"], "foo bar")

    def test_failed_replace_keeps_old_snapshot(self):
        old = _snapshot([_entry("foo", "foo")])
        ok, _ = commands.publish_snapshot(old, self.tmp)
        self.assertTrue(ok)
        new, _ = commands.validate_snapshot(_snapshot([_entry("bar", "bar")]))
        with mock.patch("kb.commands.os.replace", side_effect=OSError("磁盘满")):
            ok, detail = commands.publish_snapshot(new, self.tmp)
        self.assertFalse(ok)
        self.assertIn("磁盘满", detail)
        with open(commands.snapshot_path(self.tmp), encoding="utf-8") as fh:
            written = json.load(fh)
        self.assertEqual(written["entries"][0]["name"], "foo")
        leftovers = [
            name
            for name in os.listdir(os.path.join(self.tmp, "runtime_dump"))
            if name.startswith(".commands-")
        ]
        self.assertEqual(leftovers, [])


class ImportSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True)
        )
        self.server = os.path.join(self.tmp, "server")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(self.server, "runtime_dump"))

    def _write_raw(self, payload):
        with open(
            os.path.join(self.server, "runtime_dump", "commands.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(payload, fh)

    def test_missing_raw_file_is_not_an_error(self):
        info = commands.import_snapshot(self.server, self.data)
        self.assertEqual(info["status"], "missing")
        self.assertEqual(info["warning"], "")
        self.assertFalse(os.path.exists(commands.snapshot_path(self.data)))

    def test_publishes_valid_raw_snapshot(self):
        self._write_raw(
            _snapshot([_entry("wine", "wine info"), _entry("wine", "wine age <years>")])
        )
        info = commands.import_snapshot(self.server, self.data)
        self.assertEqual(info["status"], "published", info)
        self.assertEqual((info["count"], info["roots"]), (2, 1))
        self.assertTrue(os.path.isfile(commands.snapshot_path(self.data)))

    def test_invalid_raw_snapshot_keeps_old_published_file(self):
        self._write_raw(_snapshot([_entry("wine", "wine info")]))
        commands.import_snapshot(self.server, self.data)
        with open(commands.snapshot_path(self.data), encoding="utf-8") as fh:
            old = fh.read()

        self._write_raw({"kind": "commands", "entries": []})
        info = commands.import_snapshot(self.server, self.data)
        self.assertEqual(info["status"], "invalid")
        self.assertIn("旧快照保持不变", info["warning"])
        with open(commands.snapshot_path(self.data), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), old)

    def test_publish_failure_reports_error_and_keeps_old_snapshot(self):
        self._write_raw(_snapshot([_entry("wine", "wine info")]))
        commands.import_snapshot(self.server, self.data)
        with open(commands.snapshot_path(self.data), encoding="utf-8") as fh:
            old = fh.read()

        self._write_raw(_snapshot([_entry("wine", "wine age <years>")]))
        with mock.patch("kb.commands.os.replace", side_effect=OSError("磁盘满")):
            info = commands.import_snapshot(self.server, self.data)
        self.assertEqual(info["status"], "error")
        self.assertIn("磁盘满", info["warning"])
        with open(commands.snapshot_path(self.data), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), old)

    def test_unreadable_raw_snapshot_reports_warning(self):
        with open(
            os.path.join(self.server, "runtime_dump", "commands.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            fh.write("{ 半截")
        info = commands.import_snapshot(self.server, self.data)
        self.assertEqual(info["status"], "invalid")
        self.assertTrue(info["warning"])


class SearchCommandsTest(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.data, ignore_errors=True)
        )

    def _publish(self, entries, producer="kubejs"):
        snapshot, reason = commands.validate_snapshot(_snapshot(entries, producer))
        self.assertEqual(reason, "")
        ok, detail = commands.publish_snapshot(snapshot, self.data)
        self.assertTrue(ok, detail)

    def test_root_only_usage(self):
        self._publish([_entry("foo", "foo")])
        text = commands.search_commands("foo", data_dir=self.data)
        self.assertIn("找到 1 个匹配「foo」的命令", text)
        self.assertIn("· foo", text)

    def test_root_and_child_usage_are_both_listed(self):
        self._publish([_entry("foo", "foo"), _entry("foo", "foo bar")])
        text = commands.search_commands("foo", data_dir=self.data)
        self.assertIn("· foo", text)
        self.assertIn("· foo bar", text)
        self.assertEqual(text.count("- /foo"), 1)

    def test_keyword_hitting_usage_keeps_matching_branch_first(self):
        self._publish(
            [
                _entry("foo", "foo aaa"),
                _entry("foo", "foo bbb"),
                _entry("foo", "foo ccc"),
            ]
        )
        text = commands.search_commands("bbb", data_dir=self.data)
        self.assertIn("找到 1 个匹配「bbb」的命令", text)
        lines = [
            line.strip() for line in text.splitlines() if line.strip().startswith("·")
        ]
        self.assertEqual(lines[0], "· foo bbb")

    def test_limit_counts_roots_not_usages(self):
        self._publish(
            [
                _entry("aaa", "aaa"),
                _entry("aab", "aab"),
                _entry("aac", "aac"),
                _entry("aaa", "aaa one"),
                _entry("aaa", "aaa two"),
            ]
        )
        text = commands.search_commands("aa", limit=2, data_dir=self.data)
        self.assertIn("只显示前 2 个命令", text)
        self.assertEqual(text.count("- /aa"), 2)

    def test_runtime_root_inherits_only_vanilla_desc_and_cat(self):
        self._publish([_entry("weather", "weather clear")])
        text = commands.search_commands("weather", data_dir=self.data)
        self.assertEqual(text.count("- /weather"), 1)
        self.assertIn("来源未知", text)
        self.assertIn("权限未知", text)
        self.assertIn("天气", text)  # 内置 desc 被继承
        self.assertNotIn("原版，", text)

    def test_merged_runtime_root_is_searchable_by_vanilla_desc(self):
        # getUsage 覆盖整棵 dispatcher：快照必然含原版根，内置行随后被跳过，
        # 所以继承来的 desc 必须参与匹配，否则中文描述搜索整体失效
        self._publish([_entry("weather", "weather (clear|rain|thunder)")])
        text = commands.search_commands("天气", data_dir=self.data)
        self.assertIn("找到 1 个匹配「天气」的命令", text)
        self.assertIn("- /weather", text)
        self.assertIn("设置天气", text)

    def test_usage_display_is_capped_per_root(self):
        self._publish([_entry("foo", "foo sub%02d" % index) for index in range(10)])
        text = commands.search_commands("foo", data_dir=self.data)
        bullets = [line for line in text.splitlines() if line.strip().startswith("·")]
        self.assertEqual(len(bullets), 8)
        self.assertIn("另有 2 条用法", text)

    def test_no_result_message_when_snapshot_present(self):
        self._publish([_entry("wine", "wine info")])
        text = commands.search_commands("葡萄酒", data_dir=self.data)
        self.assertIn("运行时命令根", text)
        self.assertIn("英文命令名与参数语法", text)
        self.assertNotIn("需服务器侧导出", text)

    def test_vanilla_only_result_keeps_source_and_level(self):
        text = commands.search_commands("seed")
        self.assertIn("- /seed", text)
        self.assertIn("原版", text)
        self.assertIn("游戏内需 2 级权限", text)

    def test_redirect_is_shown_as_hint_not_executable(self):
        self._publish([_entry("alias", "alias", redirect="foo")])
        text = commands.search_commands("alias", data_dir=self.data)
        self.assertIn("重定向：alias -> foo", text)
        self.assertIn("不是完整可执行路径", text)
        self.assertNotIn("· alias", text)

    def test_rcon_producer_shows_degraded_syntax_note(self):
        self._publish([_entry("foo", "foo bar")], producer="rcon")
        text = commands.search_commands("foo", data_dir=self.data)
        self.assertIn("RCON help", text)
        self.assertIn("压缩语法", text)

    def test_kubejs_producer_shows_registered_path_note(self):
        self._publish([_entry("foo", "foo bar")])
        text = commands.search_commands("foo", data_dir=self.data)
        self.assertIn("已注册的路径", text)
        self.assertIn("不代表当前调用者必然可执行", text)
        self.assertNotIn("RCON help", text)

    def test_corrupt_canonical_warns_and_falls_back_to_vanilla(self):
        path = commands.snapshot_path(self.data)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ 坏文件")
        text = commands.search_commands("seed", data_dir=self.data)
        self.assertIn("命令快照读取失败", text)
        self.assertIn("- /seed", text)

    def test_legacy_jsonl_is_used_only_without_canonical(self):
        legacy = os.path.join(self.data, "runtime_dump", "commands.jsonl")
        os.makedirs(os.path.dirname(legacy), exist_ok=True)
        with open(legacy, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"name": "oldcmd", "syntax": "oldcmd run"}) + "\n")
        text = commands.search_commands("oldcmd", data_dir=self.data)
        self.assertIn("- /oldcmd", text)
        self.assertIn("旧版导出文件", text)

        self._publish([_entry("newcmd", "newcmd run")])
        text = commands.search_commands("oldcmd", data_dir=self.data)
        self.assertIn("未找到", text)


class RebuildFailureNoteTest(unittest.TestCase):
    def test_command_snapshot_survives_item_rebuild_failure(self):
        from kb import KnowledgeBase

        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        server = os.path.join(tmp, "server")
        os.makedirs(os.path.join(server, "runtime_dump"))
        with open(
            os.path.join(server, "runtime_dump", "commands.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump(_snapshot([_entry("wine", "wine info")]), fh)

        kb = KnowledgeBase(data_dir=os.path.join(tmp, "data"), server_dir=server)
        text = kb.rebuild()
        self.assertIn("知识库重建失败", text)  # 没有 mods/，物品库必然失败
        self.assertIn("命令快照已单独导入", text)
        self.assertTrue(os.path.isfile(commands.snapshot_path(kb.data_dir)))

    def test_rebuild_failure_surfaces_command_warning(self):
        from kb import KnowledgeBase

        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        server = os.path.join(tmp, "server")
        os.makedirs(os.path.join(server, "runtime_dump"))
        with open(
            os.path.join(server, "runtime_dump", "commands.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump({"kind": "commands", "entries": []}, fh)

        kb = KnowledgeBase(data_dir=os.path.join(tmp, "data"), server_dir=server)
        text = kb.rebuild()
        self.assertIn("知识库重建失败", text)
        self.assertIn("命令快照校验失败", text)


if __name__ == "__main__":
    unittest.main()
