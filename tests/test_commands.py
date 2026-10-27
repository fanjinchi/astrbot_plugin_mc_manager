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


def _sections(text):
    """把查询结果拆成 {根命令: [该根实际展示的 usage 行]}，只解析最终输出文本。"""
    sections = {}
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- /"):
            current = stripped[3:].split(" ")[0]
            sections[current] = []
        elif stripped.startswith("·") and current:
            sections[current].append(stripped[1:].strip())
    return sections


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


class IntentSearchTest(unittest.TestCase):
    """AC2：中文意图提炼出的英文多词查询必须召回目标根与目标 usage。

    断言最终 search_commands 文本（不传 limit，用默认 8），不检查内部评分。
    固定夹具里的 competitor_* 根各只覆盖一个概念 token，用于证明根级 AND 不误放行。
    """

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.data, ignore_errors=True)
        )

    def _publish(self, entries):
        snapshot, reason = commands.validate_snapshot(_snapshot(entries))
        self.assertEqual(reason, "")
        ok, detail = commands.publish_snapshot(snapshot, self.data)
        self.assertTrue(ok, detail)

    def _search(self, keyword):
        return _sections(commands.search_commands(keyword, data_dir=self.data))

    def _intent_entries(self):
        entries = [
            _entry("ftbquests", "ftbquests editing_mode <enabled> <player>"),
            _entry("competitor_quest", "competitor_quest list"),
            _entry("competitor_editing", "competitor_editing on"),
            _entry("waystones", "waystones list <player> all"),
            _entry("competitor_waystone", "competitor_waystone info"),
            _entry("competitor_list", "competitor_list"),
            _entry("ae2", "ae2 channelmode x2"),
            _entry("competitor_channel", "competitor_channel status"),
            _entry("competitor_mode", "competitor_mode"),
            _entry("competitor_radiation", "competitor_radiation add"),
            _entry("competitor_remove", "competitor_remove"),
        ]
        # mek 至少 10 条普通 usage；排序后目标前有 9 条，单 token 基线必然被 8 条上限折叠
        for suffix in (
            "alpha",
            "beta",
            "delta",
            "epsilon",
            "gamma",
            "iota",
            "kappa",
            "lambda",
            "mu",
        ):
            entries.append(_entry("mek", "mek %s" % suffix))
        entries.append(_entry("mek", "mek radiation removeAll"))
        entries.append(_entry("mek", "mek zeta"))
        return entries

    def test_multi_token_queries_recall_target_root_and_usage(self):
        self._publish(self._intent_entries())
        cases = {
            "quest editing": ("ftbquests", "ftbquests editing_mode <enabled> <player>"),
            "editing quest": ("ftbquests", "ftbquests editing_mode <enabled> <player>"),
            "waystone list": ("waystones", "waystones list <player> all"),
            "channel mode": ("ae2", "ae2 channelmode x2"),
            "radiation removeAll": ("mek", "mek radiation removeAll"),
            "remove radiation": ("mek", "mek radiation removeAll"),
        }
        competitors = {
            "quest editing": ("competitor_quest", "competitor_editing"),
            "editing quest": ("competitor_quest", "competitor_editing"),
            "waystone list": ("competitor_waystone", "competitor_list"),
            "channel mode": ("competitor_channel", "competitor_mode"),
            "radiation removeAll": ("competitor_radiation", "competitor_remove"),
            "remove radiation": ("competitor_radiation", "competitor_remove"),
        }
        for keyword, (root, syntax) in cases.items():
            with self.subTest(keyword=keyword):
                sections = self._search(keyword)
                self.assertIn(root, sections)
                self.assertEqual(sections[root][0], syntax)
                for competitor in competitors[keyword]:
                    self.assertNotIn(competitor, sections)

    def test_mek_baseline_collapses_then_matched_usage_moves_first(self):
        self._publish(self._intent_entries())
        target = "mek radiation removeAll"
        baseline = self._search("mek")["mek"]
        self.assertEqual(len(baseline), commands.USAGE_PER_ROOT)
        self.assertNotIn(target, baseline)  # 单根 8 条上限内看不到，必须细化关键词
        for keyword in ("radiation removeAll", "remove radiation"):
            with self.subTest(keyword=keyword):
                bullets = self._search(keyword)["mek"]
                self.assertEqual(bullets[0], target)
                self.assertIn("mek alpha", bullets)
                self.assertLess(bullets.index(target), bullets.index("mek alpha"))

    def test_default_limit_still_counts_roots_and_keeps_exact_root(self):
        entries = [_entry("common", "common status")]
        entries.extend(
            _entry("common_%02d" % index, "common_%02d status" % index)
            for index in range(1, 9)
        )
        self._publish(entries)
        sections = self._search("common")
        self.assertEqual(len(sections), 8)
        self.assertEqual(list(sections)[0], "common")


class IntentBoundaryTest(unittest.TestCase):
    """AC3：分隔符归一、精确根优先级、redirect 结构与跨字段 AND 的边界。"""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.data, ignore_errors=True)
        )

    def _publish(self, entries):
        snapshot, reason = commands.validate_snapshot(_snapshot(entries))
        self.assertEqual(reason, "")
        ok, detail = commands.publish_snapshot(snapshot, self.data)
        self.assertTrue(ok, detail)

    def _search(self, keyword):
        return _sections(commands.search_commands(keyword, data_dir=self.data))

    def test_separator_variants_hit_same_usage(self):
        self._publish(
            [
                _entry("ae2", "ae2 channelmode x2"),
                _entry("competitor_channel", "competitor_channel status"),
            ]
        )
        for keyword in (
            "channel mode",
            "channel_mode",
            "channel-mode",
            "channelmode",
            "channel__mode",
            "Channel Mode",
        ):
            with self.subTest(keyword=keyword):
                sections = self._search(keyword)
                self.assertEqual(sections["ae2"][0], "ae2 channelmode x2")
                self.assertNotIn("competitor_channel", sections)

    def test_root_name_separator_variants_share_exact_priority(self):
        self._publish(
            [
                _entry("botania-skyblock", "botania-skyblock island"),
                # 命中全部 token 但只能落到包含档，用来验证精确根仍排在最前
                _entry("botaniagarden", "botaniagarden skyblock help"),
            ]
        )
        for keyword in (
            "botania-skyblock",
            "botania_skyblock",
            "botania skyblock",
            "botaniaskyblock",
        ):
            with self.subTest(keyword=keyword):
                sections = self._search(keyword)
                self.assertEqual(list(sections)[0], "botania-skyblock")
                self.assertEqual(
                    sections["botania-skyblock"], ["botania-skyblock island"]
                )

    def test_exact_prefix_contains_order_is_preserved(self):
        self._publish(
            [
                _entry("afoo", "afoo"),
                _entry("foo", "foo"),
                _entry("foobar", "foobar"),
            ]
        )
        self.assertEqual(list(self._search("foo")), ["foo", "foobar", "afoo"])

    def test_redirect_queries_keep_alias_semantics(self):
        self._publish(
            [
                _entry("alias", "alias", redirect="target"),
                _entry("plain", "plain run"),
            ]
        )
        for keyword in ("alias target", "alias -> target"):
            with self.subTest(keyword=keyword):
                sections = self._search(keyword)
                self.assertIn("alias", sections)
                self.assertNotIn("plain", sections)
                self.assertEqual(
                    sections["alias"], []
                )  # redirect 不进入普通 matched usage
        text = commands.search_commands("alias target", data_dir=self.data)
        self.assertIn("重定向：alias -> target", text)
        # 显式 -> 只认 redirect 结构，不拿命令名/usage 凑命中
        self.assertEqual(set(self._search("->")), {"alias"})

    def test_tokens_across_fields_recall_root_but_not_matched_usage(self):
        self._publish(
            [
                _entry("mix", "mix aaa"),
                _entry("mix", "mix beta"),
                _entry("mix", "mix zeta"),
            ]
        )
        sections = self._search("beta zeta")
        self.assertIn("mix", sections)
        # 两个 token 分别落在不同 usage 上：根级 AND 成立，但不能拼成优先展示的 usage
        self.assertEqual(sections["mix"][0], "mix aaa")

    def test_inherited_desc_and_usage_tokens_do_not_form_matched_usage(self):
        # 真实风险场景：运行时根继承原版中文 desc，中文 token 命中 desc、英文 token 命中 usage
        self._publish(
            [
                _entry("weather", "weather alpha"),
                _entry("weather", "weather time <value>"),
            ]
        )
        sections = self._search("天气 time")
        self.assertIn("weather", sections)
        # 没有任何一条 usage 同时覆盖「天气」和 time，不能被拼成优先展示
        self.assertEqual(sections["weather"][0], "weather alpha")

    def test_synonym_gap_query_is_allowed_to_return_nothing(self):
        self._publish([_entry("mek", "mek radiation removeAll")])
        text = commands.search_commands("clear radiation", data_dir=self.data)
        self.assertIn("未找到", text)

    def test_separator_only_query_returns_hint(self):
        text = commands.search_commands("_-_", data_dir=self.data)
        self.assertIn("请提供搜索关键词", text)


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
