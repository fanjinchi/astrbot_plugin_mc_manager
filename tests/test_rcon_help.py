"""RCON help 采集离线回归：A/B 传输、严格解析、两阶段编排与入口生命周期。

标准库 unittest + 本机回环 fake server；这些用例验证本次改动的协议与解析语义，
不替代真机证据（P6 另有验收记录）。
"""

import asyncio
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rcon_help  # noqa: E402
from rcon_help import ScanLimits  # noqa: E402

_AUTH = 3
_AUTH_OK = 2
_RESPONSE = 0


def _frame(req_id, packet_type, payload=b""):
    data = struct.pack("<ii", req_id, packet_type) + payload + b"\x00\x00"
    return struct.pack("<i", len(data)) + data


def _help_text(lines):
    return "".join(f"/{line}\n" for line in lines)


class FakeRcon:
    """可编排的 RCON fake server：默认正常响应，另带故障开关。"""

    def __init__(self):
        self.root_help = ["help", "wine (age|info)", "alias -> wine"]
        self.final_root_help = None
        self.targeted = {
            "help": ["help <topic>"],
            "wine": ["wine age <years>", "wine info"],
            "alias": [],
        }
        self.plain_replies = {
            "list": "There are 0 of a max of 20 players online",
        }
        self.split = 4096
        self.a_delay = 0.0
        self.auth_fail = False
        self.b_text = "Unknown or incomplete command, see below for error"
        # 故障开关：只作用于命令 A 的响应
        self.eof_on_first_a = False
        self.truncated_length = False
        self.truncated_body = False
        self.bad_terminator = False
        self.bad_utf8 = False
        self.wrong_first_id = False
        self.drop_b = False
        self.withhold_a = False
        self.trailing_after_final = False
        self.late_old_id = False
        self.eof_after_first_a_packet = False
        self.events = []
        self.request_ids = []
        self.connections = 0
        self.closed_connections = 0
        self._help_count = 0
        self._last_a_id = None

    async def __aenter__(self):
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self._server.close()
        await self._server.wait_closed()

    @property
    def commands(self):
        return [event[1] for event in self.events if event[0] == "cmd"]

    async def _read_frame(self, reader, timeout=5.0):
        header = await asyncio.wait_for(reader.readexactly(4), timeout)
        (length,) = struct.unpack("<i", header)
        payload = await asyncio.wait_for(reader.readexactly(length), timeout)
        req_id, packet_type = struct.unpack("<ii", payload[:8])
        return req_id, packet_type, payload[8:-2]

    async def _handle(self, reader, writer):
        self.connections += 1
        pending_a = None
        try:
            try:
                req_id, _ptype, body = await self._read_frame(reader)
            except (asyncio.IncompleteReadError, asyncio.TimeoutError):
                return
            self.events.append(("auth", body.decode("utf-8", "replace")))
            if self.auth_fail:
                writer.write(_frame(-1, _AUTH_OK, b"password incorrect"))
                await writer.drain()
                return
            writer.write(_frame(req_id, _AUTH_OK, b""))
            await writer.drain()
            while True:
                try:
                    req_id, _ptype, body = await self._read_frame(reader)
                except (asyncio.IncompleteReadError, asyncio.TimeoutError):
                    return
                cmd = body.decode("utf-8", "replace")
                self.events.append(("cmd", cmd))
                self.request_ids.append((cmd, req_id))
                if cmd.startswith(rcon_help._B_PREFIX):
                    if pending_a is not None:
                        await self._write_a(writer, *pending_a)
                        pending_a = None
                    if not self.drop_b:
                        writer.write(_frame(req_id, _RESPONSE, self.b_text.encode()))
                        await writer.drain()
                    if self.trailing_after_final and self._help_count >= 2:
                        await asyncio.sleep(0.01)
                        writer.write(_frame(req_id + 999, _RESPONSE, b"late"))
                        await writer.drain()
                    continue
                if cmd in self.plain_replies:
                    writer.write(
                        _frame(req_id, _RESPONSE, self.plain_replies[cmd].encode())
                    )
                    await writer.drain()
                    continue
                lines, first_help = self._resolve(cmd)
                if first_help and self.eof_on_first_a:
                    return
                if first_help and self.truncated_length:
                    writer.write(struct.pack("<i", 5))
                    await writer.drain()
                    return
                if self.truncated_body:
                    writer.write(struct.pack("<i", 40) + b"\x00" * 10)
                    await writer.drain()
                    return
                if self.withhold_a:
                    pending_a = (req_id, lines)
                    continue
                if self.late_old_id and not first_help and self._last_a_id is not None:
                    writer.write(_frame(self._last_a_id, _RESPONSE, b"stale"))
                    await writer.drain()
                self._last_a_id = req_id
                await self._write_a(writer, req_id, lines)
        finally:
            self.closed_connections += 1
            try:
                writer.close()
            except Exception:
                pass

    def _resolve(self, cmd):
        if cmd == "help":
            first = self._help_count == 0
            self._help_count += 1
            if first or self.final_root_help is None:
                return self.root_help, first
            return self.final_root_help, first
        root = cmd.split(" ", 1)[1] if " " in cmd else ""
        return self.targeted.get(root, []), False

    async def _write_a(self, writer, req_id, lines):
        if self.a_delay:
            await asyncio.sleep(self.a_delay)
        if self.wrong_first_id:
            req_id += 7
        raw = _help_text(lines).encode("utf-8")
        if self.bad_utf8:
            raw = b"\xff\xfe"
        chunks = [raw[i : i + self.split] for i in range(0, len(raw), self.split)]
        if self.eof_after_first_a_packet:
            writer.write(_frame(req_id, _RESPONSE, chunks[0]))
            await writer.drain()
            writer.close()
            return
        for chunk in chunks or [b""]:
            if self.bad_terminator:
                data = struct.pack("<ii", req_id, _RESPONSE) + chunk + b"\x00\x01"
                writer.write(struct.pack("<i", len(data)) + data)
                break
            writer.write(_frame(req_id, _RESPONSE, chunk))
        await writer.drain()


def _fast_limits(**overrides):
    values = {
        "exchange_timeout": 0.3,
        "total_timeout": 5.0,
        "trailing_window": 0.05,
        "connect_timeout": 1.0,
    }
    values.update(overrides)
    return ScanLimits(**values)


async def _scan(server, limits=None):
    return await rcon_help.scan_help("127.0.0.1", server.port, "pw", limits)


class ParseRootHelpTest(unittest.TestCase):
    def test_extracts_roots_and_redirects_without_newlines(self):
        roots, redirects = rcon_help.parse_root_help(
            "/help/advancement (grant|revoke)/xp -> experience/execute"
        )
        self.assertEqual(roots, ["help", "advancement", "xp", "execute"])
        self.assertEqual(redirects, {"xp": "experience"})

    def test_bare_root_redirect_is_tolerated_as_ellipsis(self):
        _roots, redirects = rcon_help.parse_root_help("/help/alias ->   ")
        self.assertEqual(redirects, {"alias": "..."})

    def test_requires_vanilla_help_root(self):
        with self.assertRaises(rcon_help._ScanError):
            rcon_help.parse_root_help("/wine (age|info)")

    def test_rejects_empty_and_error_text(self):
        for text in ("", "   ", "Unknown command at position 0", "未知的命令：/wine"):
            with self.assertRaises(rcon_help._ScanError):
                rcon_help.parse_root_help(text)

    def test_rejects_duplicate_and_bad_structure(self):
        with self.assertRaises(rcon_help._ScanError):
            rcon_help.parse_root_help("/help/help")
        with self.assertRaises(rcon_help._ScanError):
            rcon_help.parse_root_help("/help/ERROR: not a command")

    def test_rejects_root_redirect_with_extra_usage(self):
        with self.assertRaises(rcon_help._ScanError):
            rcon_help.parse_root_help("/help/xp run -> experience")


class ParseTargetedHelpTest(unittest.TestCase):
    def test_splits_multiple_usages_without_newlines(self):
        entries = rcon_help.parse_targeted_help("/wine age <years>/wine info", "wine")
        self.assertEqual(
            [entry["syntax"] for entry in entries],
            ["wine age <years>", "wine info"],
        )

    def test_keeps_compressed_marks_in_syntax(self):
        entries = rcon_help.parse_targeted_help(
            "/execute if (block|score)/execute run ...", "execute"
        )
        self.assertEqual(
            [entry["syntax"] for entry in entries],
            ["execute if (block|score)", "execute run ..."],
        )

    def test_splits_real_redirect_forms(self):
        entries = rcon_help.parse_targeted_help(
            "/execute as <targets> -> execute", "execute"
        )
        self.assertEqual(entries[0]["redirect"], "execute")
        self.assertEqual(entries[0]["syntax"], "execute as <targets>")
        entries = rcon_help.parse_targeted_help("/xp -> experience", "xp")
        self.assertEqual(entries[0]["redirect"], "experience")

    def test_bare_arrow_normalizes_to_ellipsis(self):
        entries = rcon_help.parse_targeted_help("/alias ->   ", "alias")
        self.assertEqual(entries[0]["syntax"], "alias")
        self.assertEqual(entries[0]["redirect"], "...")

    def test_empty_response_is_legal_and_produces_no_entries(self):
        self.assertEqual(rcon_help.parse_targeted_help("", "alias"), [])
        self.assertEqual(rcon_help.parse_targeted_help("  \n", "alias"), [])

    def test_bare_targeted_root_without_redirect_fails(self):
        with self.assertRaises(rcon_help._ScanError):
            rcon_help.parse_targeted_help("/foo", "foo")

    def test_rejects_other_root_prefix_and_error_text(self):
        for text in ("/bar x", "/wine x/bar y", "Unknown command", "未知的命令"):
            with self.assertRaises(rcon_help._ScanError):
                rcon_help.parse_targeted_help(text, "wine")


class ScanOrchestrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_two_phase_scan_builds_rcon_snapshot(self):
        async with FakeRcon() as server:
            snapshot, report = await _scan(server)
        self.assertTrue(report["ok"], report["reason"])
        self.assertEqual(snapshot["producer"], "rcon")
        self.assertEqual(snapshot["count"], 4)
        self.assertEqual(
            [entry["syntax"] for entry in snapshot["entries"]],
            [
                "alias",
                "help <topic>",
                "wine age <years>",
                "wine info",
            ],
        )
        self.assertEqual(snapshot["entries"][0]["redirect"], "wine")
        self.assertEqual(report["root_count"], 3)
        self.assertEqual(report["completed_roots"], 3)
        self.assertEqual(report["requests"], 2 * (3 + 2))
        # 顺序必须是 首根 help → 逐根 targeted → 末根 help（B 哨兵不计）
        plain = [
            cmd for cmd in server.commands if not cmd.startswith(rcon_help._B_PREFIX)
        ]
        self.assertEqual(
            plain, ["help", "help help", "help wine", "help alias", "help"]
        )
        # 整次扫描 request id 不复用，且恰好 2N+4 个请求
        ids = [req_id for _cmd, req_id in server.request_ids]
        self.assertEqual(len(ids), 2 * (3 + 2))
        self.assertEqual(len(set(ids)), len(ids))
        for entry in snapshot["entries"]:
            self.assertEqual(entry["source"], "unknown")
            self.assertIsNone(entry["level"])

    async def test_multi_packet_a_and_b_only_after_first_packet(self):
        async with FakeRcon() as server:
            server.split = 12
            snapshot, report = await _scan(server)
        self.assertTrue(report["ok"], report["reason"])
        self.assertGreater(report["packets"], report["requests"])
        self.assertEqual(snapshot["count"], 4)

    async def test_root_order_change_with_same_set_is_accepted(self):
        async with FakeRcon() as server:
            server.final_root_help = list(reversed(server.root_help))
            snapshot, report = await _scan(server)
        self.assertTrue(report["ok"], report["reason"])
        self.assertEqual(report["root_count"], 3)

    async def test_root_only_root_is_not_published_as_plain_usage(self):
        async with FakeRcon() as server:
            server.root_help = ["help", "foo"]
            server.targeted = {"help": ["help <topic>"]}
            snapshot, report = await _scan(server)
        self.assertTrue(report["ok"], report["reason"])
        self.assertEqual(
            [entry["syntax"] for entry in snapshot["entries"]], ["help <topic>"]
        )


class ScanFailureTest(unittest.IsolatedAsyncioTestCase):
    async def _assert_fails(self, server, reason_part, limits=None):
        async with server:
            snapshot, report = await _scan(server, limits or _fast_limits())
        self.assertIsNone(snapshot)
        self.assertFalse(report["ok"])
        self.assertIn(reason_part, report["reason"])
        return report

    async def test_auth_failure(self):
        server = FakeRcon()
        server.auth_fail = True
        report = await self._assert_fails(server, "认证失败")
        self.assertEqual(report["phase"], "auth")

    async def test_eof_before_first_a_packet(self):
        server = FakeRcon()
        server.eof_on_first_a = True
        await self._assert_fails(server, "中断")

    async def test_truncated_length(self):
        server = FakeRcon()
        server.truncated_length = True
        await self._assert_fails(server, "帧长度非法")

    async def test_truncated_body(self):
        server = FakeRcon()
        server.truncated_body = True
        await self._assert_fails(server, "正文截断")

    async def test_bad_terminator(self):
        server = FakeRcon()
        server.bad_terminator = True
        await self._assert_fails(server, "终止字节")

    async def test_wrong_first_id(self):
        server = FakeRcon()
        server.wrong_first_id = True
        await self._assert_fails(server, "错/未知 id")

    async def test_missing_b_fails_without_resend(self):
        server = FakeRcon()
        server.drop_b = True
        report = await self._assert_fails(server, "超时")
        self.assertEqual(report["requests"], 2)

    async def test_b_must_not_be_sent_before_a_first_packet(self):
        server = FakeRcon()
        server.withhold_a = True
        await self._assert_fails(server, "超时")

    async def test_trailing_packet_after_last_b(self):
        server = FakeRcon()
        server.trailing_after_final = True
        await self._assert_fails(server, "尾随包")

    async def test_old_id_arriving_in_next_exchange(self):
        server = FakeRcon()
        server.late_old_id = True
        await self._assert_fails(server, "错/未知 id")

    async def test_bad_utf8(self):
        server = FakeRcon()
        server.bad_utf8 = True
        await self._assert_fails(server, "UTF-8")

    async def test_final_root_set_mismatch(self):
        server = FakeRcon()
        server.final_root_help = ["help", "wine (age|info)"]
        await self._assert_fails(server, "首末根集合不一致")

    async def test_targeted_parse_failure(self):
        server = FakeRcon()
        server.targeted = {"help": ["help <topic>"], "wine": ["bar x"], "alias": []}
        await self._assert_fails(server, "其它根")

    async def test_empty_entries_are_not_published(self):
        server = FakeRcon()
        server.root_help = ["help"]
        server.targeted = {"help": []}
        await self._assert_fails(server, "没有可发布")

    async def test_root_count_budget(self):
        server = FakeRcon()
        await self._assert_fails(server, "根命令数", _fast_limits(max_roots=1))

    async def test_packet_budget_per_response(self):
        server = FakeRcon()
        server.split = 5
        await self._assert_fails(
            server, "片数", _fast_limits(max_packets_per_response=1)
        )

    async def test_byte_budget_per_response(self):
        server = FakeRcon()
        server.split = 10
        await self._assert_fails(server, "字节", _fast_limits(max_response_bytes=30))

    async def test_total_budget(self):
        server = FakeRcon()
        await self._assert_fails(server, "片数", _fast_limits(max_total_packets=2))

    async def test_total_bytes_budget(self):
        server = FakeRcon()
        await self._assert_fails(server, "字节", _fast_limits(max_total_bytes=40))

    async def test_eof_after_first_a_packet(self):
        server = FakeRcon()
        server.split = 8
        server.eof_after_first_a_packet = True
        await self._assert_fails(server, "中断")

    async def test_total_timeout_fails_closed(self):
        server = FakeRcon()
        server.a_delay = 0.06
        limits = _fast_limits(
            exchange_timeout=0.5, total_timeout=0.25, trailing_window=0.01
        )
        async with server:
            snapshot, report = await _scan(server, limits)
        self.assertIsNone(snapshot)
        self.assertTrue(
            "超时" in report["reason"] or "预算" in report["reason"],
            report["reason"],
        )


class OrdinaryCommandIsolationTest(unittest.IsolatedAsyncioTestCase):
    async def test_scan_holds_send_lock_and_following_command_is_clean(self):
        from rcon_client import MinecraftRCON

        async with FakeRcon() as server:
            server.a_delay = 0.02
            rcon = MinecraftRCON("127.0.0.1", server.port, "pw")
            scan_task = asyncio.create_task(rcon.scan_help_commands(_fast_limits()))
            await asyncio.sleep(0.05)
            list_task = asyncio.create_task(rcon.execute_async("list"))
            snapshot, report = await scan_task
            result = await list_task
            await rcon.close()
        self.assertTrue(report["ok"], report["reason"])
        self.assertEqual(snapshot["producer"], "rcon")
        self.assertIn("There are 0 of a max of 20 players online", result)
        commands = server.commands
        self.assertIn("list", commands)
        self.assertGreater(commands.index("list"), commands.index("help"))

    async def test_failed_scan_does_not_poison_ordinary_commands(self):
        from rcon_client import MinecraftRCON

        async with FakeRcon() as server:
            server.trailing_after_final = True
            rcon = MinecraftRCON("127.0.0.1", server.port, "pw")
            snapshot, report = await rcon.scan_help_commands(_fast_limits())
            result = await rcon.execute_async("list")
            await rcon.close()
        self.assertIsNone(snapshot)
        self.assertFalse(report["ok"])
        self.assertIn("There are 0 of a max of 20 players online", result)

    async def test_cancelled_scan_closes_socket(self):
        async with FakeRcon() as server:
            server.withhold_a = True
            task = asyncio.create_task(_scan(server, _fast_limits()))
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            for _ in range(100):
                if server.closed_connections:
                    break
                await asyncio.sleep(0.01)
        self.assertTrue(server.closed_connections)


_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_PLUGIN_DIR))

from astrbot_plugin_mc_manager import main as plugin_main  # noqa: E402
from kb import commands as cmd_kb  # noqa: E402


class _FakeKB:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.enabled = False


class _RecordingRcon:
    """记录调用次数；不会真正连接服务器。"""

    def __init__(self, result=(None, {"ok": False})):
        self.result = result
        self.calls = 0
        self.closed = False

    async def scan_help_commands(self, limits=None):
        self.calls += 1
        return self.result

    async def close(self):
        self.closed = True


class _HangingRcon:
    def __init__(self):
        self.calls = 0
        self.cleaned = False
        self.closed = False

    async def scan_help_commands(self, limits=None):
        self.calls += 1
        try:
            await asyncio.Event().wait()
        finally:
            self.cleaned = True

    async def close(self):
        self.closed = True


class _FakeEvent:
    def __init__(self, sender="user"):
        self._sender = sender
        self.results = []

    def get_sender_id(self):
        return self._sender

    def plain_result(self, text):
        self.results.append(text)
        return text


def _rcon_snapshot():
    return rcon_help.build_snapshot(
        [
            {
                "name": "wine",
                "syntax": "wine age <years>",
                "source": "unknown",
                "level": None,
            },
            {"name": "wine", "syntax": "wine info", "source": "unknown", "level": None},
        ]
    )


def _ok_report():
    return {
        "ok": True,
        "phase": "done",
        "root": "",
        "completed_roots": 2,
        "root_count": 2,
        "requests": 8,
        "packets": 3,
        "bytes": 120,
        "elapsed_ms": 12,
        "entries": 2,
        "reason": "",
    }


class EntryCommandTest(unittest.IsolatedAsyncioTestCase):
    def _plugin(self, data_dir, rcon, admin_ids=(), mc_server_dir=""):
        plugin = plugin_main.MCManagerPlugin.__new__(plugin_main.MCManagerPlugin)
        plugin.admin_ids = set(admin_ids)
        plugin.kb = _FakeKB(data_dir)
        plugin.rcon = rcon
        plugin.mc_server_dir = mc_server_dir
        plugin._rcon_scan_lock = asyncio.Lock()
        plugin._rcon_scan_task = None
        plugin.log_watcher = None
        return plugin

    def _mods_dir(self, root, files=()):
        server_dir = os.path.join(root, "server")
        mods = os.path.join(server_dir, "mods")
        os.makedirs(mods, exist_ok=True)
        for name in files:
            if isinstance(name, tuple):
                jar_name, metadata = name
                with zipfile.ZipFile(os.path.join(mods, jar_name), "w") as jar:
                    jar.writestr("META-INF/mods.toml", metadata)
            else:
                open(os.path.join(mods, name), "wb").close()
        return server_dir

    async def test_non_admin_is_rejected_without_any_rcon_call(self):
        with tempfile.TemporaryDirectory() as data_dir:
            rcon = _RecordingRcon()
            plugin = self._plugin(data_dir, rcon, admin_ids={"admin-1"})
            event = _FakeEvent(sender="intruder")
            await _collect(plugin.cmd_kb_rcon_scan(event))
        self.assertEqual(rcon.calls, 0)
        self.assertIn("权限不足", event.results[0])

    async def test_second_invocation_does_not_queue_another_scan(self):
        with tempfile.TemporaryDirectory() as data_dir:
            rcon = _RecordingRcon()
            plugin = self._plugin(data_dir, rcon)
            await plugin._rcon_scan_lock.acquire()
            try:
                event = _FakeEvent()
                await _collect(plugin.cmd_kb_rcon_scan(event))
            finally:
                plugin._rcon_scan_lock.release()
        self.assertEqual(rcon.calls, 0)
        self.assertIn("已有 RCON help 扫描", event.results[0])

    async def test_local_kubejs_jar_rejects_before_rcon(self):
        with tempfile.TemporaryDirectory() as root:
            server_dir = self._mods_dir(root, files=["kubejs-forge-1902.jar"])
            with tempfile.TemporaryDirectory() as data_dir:
                rcon = _RecordingRcon()
                plugin = self._plugin(data_dir, rcon, mc_server_dir=server_dir)
                event = _FakeEvent()
                await _collect(plugin.cmd_kb_rcon_scan(event))
        self.assertEqual(rcon.calls, 0)
        self.assertIn("检测到 KubeJS", event.results[0])
        self.assertIn("/mc_kb_dump", event.results[0])

    async def test_jar_metadata_detects_renamed_kubejs(self):
        with tempfile.TemporaryDirectory() as root:
            server_dir = self._mods_dir(
                root,
                files=[("mystery-pack.jar", '[[mods]]\nmodId="kubejs"\n')],
            )
            with tempfile.TemporaryDirectory() as data_dir:
                rcon = _RecordingRcon()
                plugin = self._plugin(data_dir, rcon, mc_server_dir=server_dir)
                event = _FakeEvent()
                await _collect(plugin.cmd_kb_rcon_scan(event))
        self.assertEqual(rcon.calls, 0)
        self.assertIn("检测到 KubeJS", event.results[0])

    async def test_fabric_metadata_detects_kubejs(self):
        with tempfile.TemporaryDirectory() as root:
            server_dir = self._mods_dir(root, files=[])
            jar_path = os.path.join(server_dir, "mods", "renamed-pack.jar")
            with zipfile.ZipFile(jar_path, "w") as jar:
                jar.writestr("fabric.mod.json", '{"id": "kubejs"}')
            with tempfile.TemporaryDirectory() as data_dir:
                rcon = _RecordingRcon()
                plugin = self._plugin(data_dir, rcon, mc_server_dir=server_dir)
                event = _FakeEvent()
                await _collect(plugin.cmd_kb_rcon_scan(event))
        self.assertEqual(rcon.calls, 0)
        self.assertIn("检测到 KubeJS", event.results[0])

    async def test_optional_kubejs_dependency_is_not_install_evidence(self):
        toml_text = (
            '[[mods]]\nmodId="createoreexcavation"\n'
            "\n[[dependencies.createoreexcavation]]\n"
            'modId="kubejs"\nmandatory=false\n'
        )
        with tempfile.TemporaryDirectory() as root:
            server_dir = self._mods_dir(
                root, files=[("createoreexcavation.jar", toml_text)]
            )
            with tempfile.TemporaryDirectory() as data_dir:
                rcon = _RecordingRcon((_rcon_snapshot(), _ok_report()))
                plugin = self._plugin(data_dir, rcon, mc_server_dir=server_dir)
                event = _FakeEvent()
                await _collect(plugin.cmd_kb_rcon_scan(event))
        self.assertEqual(rcon.calls, 1)
        self.assertNotIn("检测到 KubeJS", "\n".join(event.results))

    async def test_corrupted_jar_does_not_break_receipt(self):
        # 坏 jar（deflate 流损坏）抛 zlib.error 时必须按“无证据”处理，
        # 不能把异常抛到回执之前，让管理员看不到任何结果。
        toml_text = '[[mods]]\nmodId="some_mod"\n'
        with tempfile.TemporaryDirectory() as root:
            server_dir = self._mods_dir(root, files=[("damaged.jar", toml_text)])
            with tempfile.TemporaryDirectory() as data_dir:
                rcon = _RecordingRcon((_rcon_snapshot(), _ok_report()))
                plugin = self._plugin(data_dir, rcon, mc_server_dir=server_dir)
                event = _FakeEvent()
                with mock.patch(
                    "zipfile.ZipFile.read", side_effect=zlib.error("bad deflate")
                ):
                    await _collect(plugin.cmd_kb_rcon_scan(event))
        self.assertEqual(rcon.calls, 1)
        self.assertTrue(event.results)
        self.assertIn("✓ RCON help 命令树已发布", event.results[-1])

    async def test_leftover_kubejs_dir_only_warns_and_scan_publishes(self):
        with tempfile.TemporaryDirectory() as root:
            server_dir = self._mods_dir(root, files=[])
            os.makedirs(os.path.join(server_dir, "kubejs"), exist_ok=True)
            with tempfile.TemporaryDirectory() as data_dir:
                rcon = _RecordingRcon((_rcon_snapshot(), _ok_report()))
                plugin = self._plugin(data_dir, rcon, mc_server_dir=server_dir)
                event = _FakeEvent()
                await _collect(plugin.cmd_kb_rcon_scan(event))
                path = cmd_kb.snapshot_path(data_dir)
                self.assertTrue(os.path.isfile(path))
                with open(path, encoding="utf-8") as fh:
                    published = json.load(fh)
                found = cmd_kb.search_commands("wine", data_dir=data_dir)
        self.assertEqual(rcon.calls, 1)
        joined = "\n".join(event.results)
        self.assertIn("残留 kubejs/ 目录", joined)
        self.assertIn("✓ RCON help 命令树已发布", joined)
        self.assertIn("2N+4", joined)
        self.assertIn("wine", found)
        self.assertIn("纯根命令可能未收录", found)
        self.assertIn("暂停其它 RCON 写入者", joined)
        self.assertIn("fallback 环境", joined)
        self.assertEqual({e["source"] for e in published["entries"]}, {"unknown"})
        self.assertTrue(all(e["level"] is None for e in published["entries"]))

    async def test_no_local_dir_and_disabled_kb_still_publishes(self):
        with tempfile.TemporaryDirectory() as data_dir:
            rcon = _RecordingRcon((_rcon_snapshot(), _ok_report()))
            plugin = self._plugin(data_dir, rcon, mc_server_dir="")
            event = _FakeEvent()
            await _collect(plugin.cmd_kb_rcon_scan(event))
            self.assertTrue(os.path.isfile(cmd_kb.snapshot_path(data_dir)))
        self.assertEqual(rcon.calls, 1)
        self.assertIn("✓ RCON help 命令树已发布", event.results[-1])

    async def test_failure_receipt_contains_phase_root_and_progress(self):
        report = {
            "ok": False,
            "phase": "help",
            "root": "wine",
            "completed_roots": 1,
            "root_count": 2,
            "requests": 4,
            "packets": 2,
            "bytes": 64,
            "elapsed_ms": 9,
            "reason": "help wine 返回裸根行",
            "unexpected": False,
        }
        with tempfile.TemporaryDirectory() as data_dir:
            rcon = _RecordingRcon((None, report))
            plugin = self._plugin(data_dir, rcon)
            event = _FakeEvent()
            await _collect(plugin.cmd_kb_rcon_scan(event))
            self.assertFalse(os.path.exists(cmd_kb.snapshot_path(data_dir)))
        joined = event.results[-1]
        self.assertIn("阶段：help", joined)
        self.assertIn("失败根：wine", joined)
        self.assertIn("已完成 1/2", joined)
        self.assertIn("旧命令快照保持不变", joined)

    async def test_validate_failure_keeps_old_snapshot_bytes(self):
        with tempfile.TemporaryDirectory() as data_dir:
            good, reason = cmd_kb.validate_snapshot(_rcon_snapshot())
            self.assertEqual(reason, "")
            ok, error = cmd_kb.publish_snapshot(good, data_dir)
            self.assertTrue(ok, error)
            path = cmd_kb.snapshot_path(data_dir)
            with open(path, "rb") as fh:
                before = fh.read()
            broken = dict(_rcon_snapshot())
            broken["count"] = 99
            rcon = _RecordingRcon((broken, _ok_report()))
            plugin = self._plugin(data_dir, rcon)
            event = _FakeEvent()
            await _collect(plugin.cmd_kb_rcon_scan(event))
            with open(path, "rb") as fh:
                after = fh.read()
        self.assertEqual(before, after)
        self.assertIn("未通过共享校验", event.results[-1])

    async def test_terminate_cancels_production_scan_and_closes_socket(self):
        from rcon_client import MinecraftRCON

        async with FakeRcon() as server:
            server.a_delay = 0.05
            with tempfile.TemporaryDirectory() as data_dir:
                rcon = MinecraftRCON("127.0.0.1", server.port, "pw")
                plugin = self._plugin(data_dir, rcon)
                event = _FakeEvent()
                consumer = asyncio.create_task(_collect(plugin.cmd_kb_rcon_scan(event)))
                for _ in range(200):
                    if "help" in server.commands:
                        break
                    await asyncio.sleep(0.01)
                self.assertIn("help", server.commands)
                await plugin.terminate()
                with self.assertRaises(asyncio.CancelledError):
                    await consumer
                for _ in range(200):
                    if server.closed_connections:
                        break
                    await asyncio.sleep(0.01)
        self.assertTrue(server.closed_connections)

    async def test_terminate_cancels_active_scan_and_closes_socket(self):
        with tempfile.TemporaryDirectory() as data_dir:
            rcon = _HangingRcon()
            plugin = self._plugin(data_dir, rcon)
            event = _FakeEvent()
            consumer = asyncio.create_task(_collect(plugin.cmd_kb_rcon_scan(event)))
            for _ in range(100):
                if rcon.calls:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(rcon.calls, 1)
            await plugin.terminate()
            with self.assertRaises(asyncio.CancelledError):
                await consumer
        self.assertTrue(rcon.cleaned)
        self.assertTrue(rcon.closed)


async def _collect(generator):
    return [item async for item in generator]
