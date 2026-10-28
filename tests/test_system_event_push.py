"""系统事件推送开关的离线回归：四类事件互不串台、未知类型不推。

不验证真实群推送（那需要真机），只锁定"哪个开关控制哪类事件、推什么文本"这条契约，
以及 _conf_schema.json 的分组子键与代码里的四类事件保持一致。
"""

import json
import os
import sys
import unittest

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_PLUGIN_DIR))

from astrbot_plugin_mc_manager import main as plugin_main  # noqa: E402

# schema 子键 -> (回调名, 回调参数, 预期推送文本)
_CASES = {
    "join": ("_on_player_join", ("Steve",), "玩家 Steve 加入了游戏"),
    "leave": ("_on_player_leave", ("Steve",), "玩家 Steve 离开了游戏"),
    "death": ("_on_player_death", ("Steve", "Steve was slain by Zombie"), "Steve was slain by Zombie"),
    "advancement": (
        "_on_player_advancement",
        ("Steve", "Stone Age"),
        "玩家 Steve 达成了成就 [Stone Age]",
    ),
}


def _make_plugin(*enabled):
    """构造只带推送开关和假转发器的插件实例（不连 RCON、不起日志监听）。"""
    plugin = plugin_main.MCManagerPlugin.__new__(plugin_main.MCManagerPlugin)
    plugin.system_event_push = {key: key in enabled for key in _CASES}
    # 本文件只测群推送；上下文注入另有开关，避免真去投递事件
    plugin.enable_system_event_context = False
    plugin.sent = []

    async def _record(text):
        plugin.sent.append(text)

    plugin._forward_to_bound_group = _record
    return plugin


async def _fire(plugin, event_type):
    callback_name, args, _ = _CASES[event_type]
    await getattr(plugin, callback_name)(*args)


class SystemEventPushSwitchTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_off_pushes_nothing(self):
        plugin = _make_plugin()
        for event_type in _CASES:
            await _fire(plugin, event_type)
        self.assertEqual(plugin.sent, [])

    async def test_each_type_only_pushes_its_own_event(self):
        for enabled in _CASES:
            with self.subTest(enabled=enabled):
                plugin = _make_plugin(enabled)
                for event_type in _CASES:
                    await _fire(plugin, event_type)
                self.assertEqual(plugin.sent, [_CASES[enabled][2]])

    async def test_two_switches_push_their_own_texts(self):
        plugin = _make_plugin("death", "advancement")
        for event_type in ("death", "advancement"):
            await _fire(plugin, event_type)
        self.assertEqual(plugin.sent, [_CASES["death"][2], _CASES["advancement"][2]])

    async def test_unknown_event_type_is_ignored(self):
        plugin = _make_plugin(*_CASES)
        await plugin._forward_system_event("server_start", "服务器已启动")
        await plugin._forward_system_event("", "空类型")
        self.assertEqual(plugin.sent, [])


class SystemEventContextIndependentTest(unittest.IsolatedAsyncioTestCase):
    async def test_context_injection_ignores_push_switches(self):
        plugin = _make_plugin()  # 推送全关
        plugin.enable_system_event_context = True
        injected = []

        async def _fake_send(player, message):
            injected.append(message)

        plugin._send_system_event = _fake_send
        await _fire(plugin, "join")
        self.assertEqual(plugin.sent, [])
        self.assertEqual(injected, ["[系统消息] Steve 加入了游戏"])


class SystemEventPushSchemaTest(unittest.TestCase):
    def test_schema_group_matches_four_push_types(self):
        schema_path = os.path.join(_PLUGIN_DIR, "_conf_schema.json")
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
        group = schema["system_event_push"]
        self.assertEqual(group["type"], "object")
        self.assertEqual(set(group["items"]), set(_CASES))
        for key, item in group["items"].items():
            with self.subTest(key=key):
                self.assertEqual(item["type"], "bool")
                self.assertIs(item["default"], False)
        self.assertNotIn("enable_system_event_forward", schema)
