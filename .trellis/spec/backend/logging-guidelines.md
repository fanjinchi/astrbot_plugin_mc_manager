# Logging Guidelines

> How logging is done in this project.

---

## Overview

插件进程内统一用 AstrBot 的 logger：`from astrbot.api import logger`。**不要**用
`logging.getLogger(__name__)`，那样不会进 AstrBot 的日志面板。

```python
from astrbot.api import logger
```
（`main.py:9`、`rcon_client.py:10`、`log_client.py:12`）

一个例外，在"框架外"的代码：

- `tools/*.py` 与 `text_outbound.py` **完全不产生日志**（0 处 logger/print）。信息随返回字符串回到 LLM/用户；排障看调用侧或
  RCON 层那条命令日志。新增 tools 函数请保持这一点。

当前分布：`info` 34 处、`error` 28 处、`warning` 5 处、`debug` 3 处。

---

## Log Levels

| 级别 | 用在哪 | 现实例子 |
|---|---|---|
| debug | 被过滤的中间响应等诊断细节 | `logger.debug(f"过滤掉中间响应: {response_text}")`（`main.py`） |
| info | 生命周期、每条 RCON 命令+响应、每个 MC 事件/聊天 | `logger.info(f"执行命令: {command}, 响应: {response}")`（`rcon_client.py:74`）；`logger.info(f"[MC事件] 玩家 {player} 加入了游戏")`（`main.py:175`） |
| warning | 可自愈的异常：重连尝试、断连、连接测试失败 | `logger.warning(f"RCON连接异常 (尝试 1/2): ...")`（`rcon_client.py:77`）；`logger.warning("与日志服务器的连接已断开")`（`main.py:162`） |
| error | 最终失败：重试耗尽、建连失败、回调异常、心跳超时 | `logger.error(f"提交MC消息失败: {e}")`（`main.py:259`）；`logger.error(f"服务端心跳超时（超过{self.HEARTBEAT_TIMEOUT}秒），断开连接")`（`log_client.py:275`） |

---

## Structured Logging

**没有结构化日志**：不打 JSON、不带 `extra` 字段、不做统一 request id。就是中文 + f-string 插值。

约定：

- 事件类日志统一 `[MC事件]` 前缀（`main.py:153/166/180/194`、`log_client.py:290/302/315/327`）；
  聊天用 `[MC聊天] <玩家> 内容`（`log_client.py:341`）。
- 错误日志写法固定为 `logger.error(f"<做什么>失败: {e}")`，冒号后直接异常对象；不要写英文、不要拼接堆栈。
- 命令日志保留完整命令与响应（`rcon_client.py:74`）——这是排障主入口，包含玩家名/物品名是刻意的。

---

## What to Log

- 插件生命周期：加载（`main.py:111`）、日志监控启动（`:118`）、停止（`:322`）。
- 每条 RCON 命令 + 原始响应（`rcon_client.py:74`）。
- 每个 MC 事件（登入/登出/成就/死亡）和玩家聊天（`log_client.py:279-360`）。
- 所有失败路径，必须带"在做什么"的上下文。

---

## What NOT to Log

- **RCON 密码 / 任何配置密钥**。现状正确：连接日志只打 `host:port`（`main.py:111`、`rcon_client.py:38`），
  `rcon_password` 从未进日志。新增配置项同理。
- **完整 UMO 串**（含群号）不要进日志或返回给模型；报错时说明缺哪个配置项即可（`main.py:648-652`）。
- **每个 LLM 工具的逐次 info 日志**：现有 12 个 `tool_*` 里一条日志都没有，调用链由 `execute_async` 那条
  命令日志覆盖。新增工具不要加 `logger.info("调用工具 xxx")`。
- **循环里的逐条 debug 刷屏**（如每个玩家一行）；心跳/重连已有节流，别在热路径加日志。
