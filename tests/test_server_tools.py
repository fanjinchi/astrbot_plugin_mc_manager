import unittest

from tools import server_tools


class _RecordingRcon:
    def __init__(self):
        self.calls = []

    async def execute_async(self, command):
        self.calls.append(command)
        return "ok"


class ExecuteCommandGateTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rcon = _RecordingRcon()
        server_tools.set_rcon(self.rcon)
        server_tools.set_dangerous_commands_enabled(False)

    async def asyncTearDown(self):
        server_tools.set_dangerous_commands_enabled(False)
        server_tools.set_rcon(None)

    async def assert_blocked(self, command, expected_name=None):
        result = await server_tools.execute_command(command)
        self.assertIn("危险命令", result, command)
        if expected_name:
            self.assertIn(f"'{expected_name}'", result, command)
        self.assertEqual(self.rcon.calls, [], command)

    async def test_direct_dangerous_commands_are_blocked(self):
        for command in ("stop", "op", "deop", "ban", "ban-ip", "pardon", "pardon-ip"):
            with self.subTest(command=command):
                await self.assert_blocked(command, command)

    async def test_direct_command_normalization_is_blocked(self):
        variants = (
            ("  /STOP", "stop"),
            ("\tminecraft:Op  Steve", "op"),
            ("/MINECRAFT:BAN-IP 127.0.0.1", "ban-ip"),
        )
        for command, expected_name in variants:
            with self.subTest(command=command):
                await self.assert_blocked(command, expected_name)

    async def test_execute_wrappers_are_blocked(self):
        variants = (
            "execute run stop",
            "/execute as @a run /op Steve",
            "execute as @a at @s run minecraft:ban Steve",
            "minecraft:execute run minecraft:stop",
            "execute run execute as @a run execute at @s run deop Steve",
            "execute if score run run matches 0..1 run op Steve",
            "execute store result storage run run byte 1 run stop",
        )
        for command in variants:
            with self.subTest(command=command):
                await self.assert_blocked(command)

    async def test_whitelist_write_operations_are_blocked(self):
        for operation in ("on", "off", "add", "remove", "reload"):
            with self.subTest(operation=operation):
                await self.assert_blocked(f"whitelist {operation}", "whitelist")
        await self.assert_blocked("execute run whitelist off", "whitelist")

    async def test_whitelist_list_is_allowed(self):
        for command in ("whitelist list", "execute run whitelist list"):
            with self.subTest(command=command):
                result = await server_tools.execute_command(command)
                self.assertEqual(result, f"执行命令 '{command}': ok")
                self.assertEqual(self.rcon.calls[-1], command)

    async def test_normal_commands_and_execute_clauses_are_allowed(self):
        commands = (
            "say hello",
            "execute align xyz run say ok",
            "execute anchored feet run say ok",
            "execute as @a run say ok",
            "execute at @a run say ok",
            "execute facing 0 0 0 run say ok",
            "execute facing entity @a eyes run say ok",
            "execute in minecraft:the_nether run say ok",
            "execute positioned 0 0 0 run say ok",
            "execute positioned as @a run say ok",
            "execute rotated 0 0 run say ok",
            "execute rotated as @a run say ok",
            "execute if biome 0 0 0 minecraft:plains run say ok",
            "execute unless block 0 0 0 minecraft:stone run say ok",
            "execute if blocks 0 0 0 1 1 1 2 2 2 all run say ok",
            "execute if data block 0 0 0 Items run say ok",
            "execute if data entity @p SelectedItem run say ok",
            "execute if data storage run run run say ok",
            "execute if dimension minecraft:overworld run say ok",
            "execute if entity @a run say ok",
            "execute if function run run say ok",
            "execute if loaded 0 0 0 run say ok",
            "execute if predicate run run say ok",
            "execute if score run run matches 0..1 run say ok",
            "execute if score @p objective > @q other_objective run say ok",
            "execute store result block 0 0 0 Items byte 1 run say ok",
            "execute store success bossbar run value run say ok",
            "execute store result entity @p Health float 1 run say ok",
            "execute store result score run run run say ok",
            "execute store result storage run run byte 1 run say ok",
        )
        for command in commands:
            with self.subTest(command=command):
                result = await server_tools.execute_command(command)
                self.assertEqual(result, f"执行命令 '{command}': ok")
                self.assertEqual(self.rcon.calls[-1], command)

    async def test_run_and_stop_in_arguments_do_not_trigger_gate(self):
        commands = (
            'execute as @a[name="run stop"] run say hello',
            'execute as @e[nbt={CustomName:\'{"text":"run stop"}\'}] run say hello',
            'execute run tellraw @a {"text":"please stop"}',
            "execute run say run stop",
            'tellraw @a {"text":"execute run stop"}',
        )
        for command in commands:
            with self.subTest(command=command):
                result = await server_tools.execute_command(command)
                self.assertEqual(result, f"执行命令 '{command}': ok")
                self.assertEqual(self.rcon.calls[-1], command)

    async def test_unparseable_commands_fail_closed(self):
        commands = (
            "execute frobnicate run stop",
            "execute if score run run",
            "execute run",
            'execute as @a[name="unterminated] run stop',
        )
        for command in commands:
            with self.subTest(command=command):
                result = await server_tools.execute_command(command)
                self.assertIn("无法可靠解析", result)
                self.assertEqual(self.rcon.calls, [], command)

    async def test_empty_command_is_rejected(self):
        result = await server_tools.execute_command(" \t ")
        self.assertIn("命令不能为空", result)
        self.assertEqual(self.rcon.calls, [])

    async def test_enabled_switch_preserves_raw_rcon_behavior(self):
        server_tools.set_dangerous_commands_enabled(True)
        commands = ("stop", "execute run op Steve", "execute unknown run stop")
        for command in commands:
            with self.subTest(command=command):
                result = await server_tools.execute_command(command)
                self.assertEqual(result, f"执行命令 '{command}': ok")
                self.assertEqual(self.rcon.calls[-1], command)


if __name__ == "__main__":
    unittest.main()
