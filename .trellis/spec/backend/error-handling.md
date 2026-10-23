# Error Handling

> How errors are handled in this project.

---

## Overview

本项目有两个错误面，任何新代码都要同时想清楚这两面：

1. **给 LLM / 用户的**：返回中文结果字符串，错误前缀 `错误:`（`tools/`）或 `✗`/`❌`（`main.py` 的脚本/QQ 工具）。
   工具函数**不抛异常**，因为返回值会被 AstrBot 原样回灌给模型。
2. **给运维的**：`logger.error` / `logger.warning`，见 logging-guidelines。

核心原则：**异常不允许穿透到 AstrBot 的事件管线**。日志回调是 `asyncio.create_task` 调度的
（`log_client.py:347`），抛出去就是 unhandled task exception，没人接。

---

## Error Types

**没有自定义异常类。** 全项目唯一主动 `raise` 的是注入守卫：

```python
def get_rcon() -> "MinecraftRCON":
    """获取RCON客户端"""
    if _rcon is None:
        raise RuntimeError("RCON客户端未初始化")
    return _rcon
```
（`tools/game_tools.py:22-26`，四个 tools 模块各一份）

这是**编程错误**（`_inject_rcon()` 之前就调用了工具），不是运行时可恢复状态：不捕获、不翻译、不为它加
fallback。新增 tools 模块照抄这个守卫。

---

## Error Handling Patterns

### A. RCON 层：连接类异常重试，其余立即返回（`rcon_client.py:55-86`）

```python
max_retries = 2
for attempt in range(max_retries):
    try:
        client = await self._ensure_connection()
        response = await client.send_cmd(command)
        logger.info(f"执行命令: {command}, 响应: {response}")
        return response if response else "命令执行成功（无返回信息）"
    except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError, OSError) as e:
        logger.warning(f"RCON连接异常 (尝试 {attempt + 1}/{max_retries}): {e}")
        await self._reconnect()
        if attempt == max_retries - 1:
            error_msg = f"无法连接到服务器 {self.host}:{self.port}，请检查服务器是否启动且RCON已启用"
            logger.error(error_msg)
            return f"错误: {error_msg}"
    except Exception as e:
        error_msg = f"执行命令时出错: {str(e)}"
        logger.error(error_msg)
        return f"错误: {error_msg}"
```

要点：只对**连接类**异常重试；其他异常立即返回；`execute_async` 的返回类型永远是 `str`，调用方不需要包
`try`。成功且无输出时返回"命令执行成功（无返回信息）"，所以**不要用真假值判断成败**，要看 `错误:` 前缀。

### B. 参数校验失败：直接返回错误串，不发命令（`tools/world_tools.py:58-59`）

```python
if weather_type not in ["clear", "rain", "thunder"]:
    return f"错误: 无效的天气类型 '{weather_type}'，可选值：clear、rain、thunder"
```

### C. 危险命令闸门：配置开关 + 命令白名单（`tools/server_tools.py:203-213`）

```python
dangerous_commands = ["stop", "ban-ip"]
cmd_base = command.split()[0].lower() if command else ""

if cmd_base in dangerous_commands and not _enable_dangerous_commands:
    return f"错误: 命令 '{cmd_base}' 是危险命令，已被禁用。"
```

### D. 事件管线边界：整段 try/except + 只记日志（`main.py:200-259`、`:261-313`、`:337-382`）

```python
async def _send_fake_event(self, player: str, message: str):
    try:
        ...
    except Exception as e:
        logger.error(f"提交MC消息失败: {e}")
```

这些方法是日志回调，由 `LogClient` 用 `create_task` 调度；必须自己吞异常并记录。

### E. 资源清理：允许裸 `except:`（`rcon_client.py:51/162/175`、`log_client.py:145`、`log_server.py:126/244/272`）

```python
try:
    await self._client.close()
except:
    pass
```

**仅限** `close()` / `wait_closed()` 这类 best-effort 清理。业务逻辑里禁止裸 `except:`——它会吞掉
`CancelledError` 和 `KeyboardInterrupt`，比不写还糟。

---

## API Error Responses

没有 HTTP API。对外的"响应"就是工具返回值，格式约定：

| 场景 | 格式 | 例子 |
|---|---|---|
| tools 层失败 | `错误: <中文原因>，可选值：...` | `错误: 无效的天气类型 'snow'，可选值：clear、rain、thunder` |
| 权限不足 | `权限不足：用户 <id> 不在管理员列表中` | `main.py:482-484` |
| 危险命令被禁用 | `错误: 命令 '<cmd>' 是危险命令，已被禁用。` | `tools/server_tools.py:210` |
| 处理成功 | `<做了什么>: <RCON 原始响应>` | `给予 Steve 5个 minecraft:diamond: Given ...` |
| 功能未启用 | `❌ 未启用统一上下文功能(enable_unified_context)...` | `main.py` `tool_send_to_qq_group` |

---

## Common Mistakes

- **在 `tool_*` 里 raise。** 模型拿到的是框架异常而不是可读原因；现有 12 个工具（`grep -c 'async def tool_'`）无一例外都是返回字符串。
- **对 `execute_async` 的结果做 `if not result:` 判断。** 成功无输出时返回固定文案（真值），失败时是
  `错误:` 前缀；用前缀判断，别用真假值。
- **给整个 LLM 工具再包一层 try/except 兜底。** 现有代码不这样做（靠 execute_async 不抛），重复兜底只会
  丢堆栈、把可定位的 bug 变成"未知错误"。
- **忘记权限检查。** 新工具默认必须 `_check_permission`；免检只有 3 个只读工具：
  `list_players`、`search_mc_items`、`search_mc_commands`（物品/命令知识库查询）。
  知识库的 `mc_kb_rebuild` / `mc_kb_status` 是管理员指令，同样走 `_check_permission`。
- **依赖 `is_admin()` 的返回类型。** `main.py:447-470` 声明 `-> bool`，但非管理员路径走完分支隐式返回
  `None`；`if not self.is_admin(...)` 靠假值侥幸成立。新代码不要依赖它返回严格 bool（修的时候补
  `return False`，见 quality-guidelines 已知债务）。
- **把异常信息原样丢给 LLM。** 现有做法是翻译成中文操作建议（"请检查服务器是否启动且RCON已启用"），
  堆栈只进日志。
