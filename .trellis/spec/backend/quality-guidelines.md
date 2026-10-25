# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

现实约束先说清楚：**本项目没有测试套件、没有 lint 配置、没有 CI**（没有 `pyproject.toml`/`ruff.toml`/
`pytest.ini`，全仓 0 个 `test_*.py`）。质量靠三件事兜：编译检查、真服务器联调、review 清单。

因此：不要说"测试通过"。能说的是"编译通过 + 真机验证过哪条链路"。

工具链现状：Python 3.12（AstrBot 要求 3.10+），运行时依赖只有 `aio-mc-rcon>=1.4.2`
（`requirements.txt`）。

---

## Forbidden Patterns

- **新增 `@filter.llm_tool` 却不做权限检查。** 只读查询是唯一例外（3 个，见 error-handling）。
- **在 `tools/*.py` 里 import astrbot / 打日志 / print。** 这一层保持无框架依赖，便于独立测试与复用。
- **在 `main.py` 里直接拼 MC 命令发 RCON**，实现应下沉到 `tools/`。豁免：游戏内聊天出栈文本统一走
  `text_outbound.py` 纯函数（`build_tellraw_commands`，带 1460B 字节预算切段），`main.py` 只负责调用——
  这是 2026-10 重构确立的特例，替代旧 `_send_single_mc_message` 的内联拼接。
- **依赖 `self.is_admin()` 的返回值类型**（隐式返回 `None`，见"已知债务"）。
- **用裸 `except:` 包业务逻辑**；只允许用于 `close()`/`wait_closed()` 这类清理。
- **绕过 `enable_dangerous_commands` 开关**把 `stop`/`ban-ip` 之类命令暴露给 LLM。
- **把 RCON 密码、完整 UMO 串写进日志或返回给模型。**
- **调用不存在的同步 `rcon.execute()`。** 客户端只有 `execute_async`（死代码已于 2026-10 清除）。
- **引入未在 `requirements.txt` 声明的第三方依赖。**
- **给 `execute_async` 返回值加 `if not result` 式成败判断**（见 error-handling）。

---

## Required Patterns

### 1. LLM 工具契约（最容易写错的地方）

```python
@filter.llm_tool(name="give_item")
async def tool_give_item(self, event: AstrMessageEvent, player: str, item: str, count: int = 1) -> str:
    """给予玩家物品

    Args:
        player(string): 要给予物品的玩家名称
        item(string): 物品ID，如diamond、iron_sword
        count(number): 物品数量，默认1
    """
    has_permission, error_msg = self._check_permission(event)
    if not has_permission:
        return error_msg
    return await game_tools.give_item(player, item, count)
```

- docstring 第一行是工具描述，模型靠它决定何时调用。
- `Args:` 里必须是 `参数名(类型): 中文说明`，类型只写 `string` / `number` / `boolean`。
  AstrBot 用这套格式生成 function schema，写成 `player: str` 或漏掉 Args 会让模型调不动。
- `event: AstrMessageEvent` 恒为第一个参数，不写进 Args。
- 返回 `str`，中文，带执行结果。
- 先 `_check_permission`，再转发；不要在这层写业务逻辑。

### 2. tools 函数契约

```python
async def give_item(player: str, item: str, count: int = 1) -> str:
    """给予玩家物品

    Args:
        player(string): 要给予物品的玩家名称，使用@p表示最近的玩家，@a表示所有玩家
        ...
    """
    rcon = get_rcon()
    item = normalize_mc_id(item)   # 无命名空间才补 minecraft:，模组 ID 原样保留
    count = max(1, min(count, 64))
    result = await rcon.execute_async(f"give {player} {item} {count}")
    return f"给予 {player} {count}个 {item}: {result}"
```

同样的 docstring 格式（AstrBot 据 docstring 生成 LLM 工具 schema 与参数说明，`Args` 必须
`name(type): 说明`）；参数归一化 + 边界钳制在发命令前做；返回"做了什么 + RCON 原始响应"。

资源 ID 归一化统一用 `tools/id_utils.py` 的 `normalize_mc_id()`：**只在没有命名空间分隔符时补
`minecraft:`**，`thermal:tin_ingot` 这类模组完整 ID 必须原样通过。不要再写
`if not x.startswith("minecraft:")`——那会把模组 ID 变成 `minecraft:thermal:tin_ingot`。

### 3. 权限

`_check_permission` 先行，返回 `(bool, 错误文案)`。免检只读工具必须能在 `grep -n "无需权限"` 里查到，
新增免检项要在这里列名。当前 3 个：`list_players`、`search_mc_items`、`search_mc_commands`
（物品/命令知识库查询）。whitelist/banlist 属管理功能（游戏内 3 级权限），查询也走 `execute_command`。

`@filter.command` 指令默认也要权限检查（知识库的 `mc_kb_rebuild` / `mc_kb_status` 都是管理员指令）。

### 4. 异步纪律

所有 RCON 交互 `await rcon.execute_async(...)`；回调一律 `async def`（`LogWatcher` 用 `create_task` 调度）；
阻塞式 IO（读日志文件）用 `asyncio` 原语而非同步调用。

### 5. 命令拼接与转义

`tellraw` 等 JSON 文本命令要做双引号转义（`tools/server_tools.py:67-68`、`main.py:437` 的
`replace('\\', '\\\\').replace('"', '\\"')`）。新增拼 JSON 的命令必须复用同样的转义；不拼接文件路径、
不拼 shell。

### 6. 输入归一化

枚举类参数先做中文→英文映射再校验，让 LLM/玩家能直接说中文：
游戏模式 `tools/game_tools.py:86-96`、天气 `tools/world_tools.py:46-59`、时间 `tools/world_tools.py:82-93`。

### 7. 配置

`self.config.get("key", <与 _conf_schema.json 一致的默认值>)`；配置项必须同时出现在 schema 和读取处，
两处默认值一致；用户可见配置还要同步 README。

### 8. 类型与注释

- 只用 Python 3.10+ 特性；集合用内建泛型 `list[str]` / `tuple[bool, str]`，可空用 `typing.Optional`
  （两种风格并存是现状，别为统一而大改）。
- 公开函数写全类型标注。
- 注释用中文，解释"为什么"；历史决策写进注释保留（范例：`main.py:46-47` 记录唤醒词配置已移除）。

---

## Testing Requirements

没有自动化测试，验证分三档，按改动范围选：

1. **必做：编译检查**
   ```bash
   python3 -m compileall -q main.py rcon_client.py log_watcher.py text_outbound.py runtime_dump.py tools/ kb/
   ```
2. **改了导入/装配：导入冒烟**。确认 `python3 -c "import ast; ast.parse(open('main.py').read())"` 之外，
   重点核对 `_inject_rcon()` 里有没有漏注入或写错模块名。
3. **改了 RCON 行为：真机验证**。装到 AstrBot，`/test_connection`（`main.py:671`）看 RCON；`/test_log`
   （`:690`）看日志链路；再让 LLM 实际调一次改动的工具，看游戏内效果。
4. **改了 `log_watcher.py`**：用临时目录造一个假 latest.log 跑行为验证（解析正确性 / 不回放历史 /
   轮转与重启恢复 / stop 无幽灵任务），脚本放 /tmp，不进仓库。

不要为了一次改动去造一个测试框架来"证明"正确性；也不要写只覆盖 mock 的测试当作真机验证。

---

## Code Review Checklist

review 时逐条对：

- [ ] 编译通过；改动文件无 `SyntaxError`/`NameError` 级别的低级错。
- [ ] 新工具三处同名一致（装饰器 `name` / `tool_*` / `tools` 函数），`Args` 用 `name(type): 说明` 格式。
- [ ] 权限路径穷尽：需要权限的会不会被绕过？只读的确实只读？
- [ ] 失败路径返回中文错误串并打日志；有没有把成功误判为失败（`execute_async` 的返回语义）。
- [ ] 是否破坏 Fabric/Forge/NeoForge 通用性、是否假定某个 MC 版本的命令语法。
- [ ] 新增资源是否在 `terminate()` 或 `close()` 里清理。
- [ ] `_conf_schema.json` / README 是否跟着改（用户可见配置必须两处同步）。
- [ ] 日志里没有密码/群号/整段脚本。

---

## 已知债务（记录现状，修复是独立任务）

| 位置 | 现状 | 影响 |
|---|---|---|
| `main.py:448-470` | `is_admin()` 声明 `-> bool`，非管理员分支隐式返回 `None` | 靠假值侥幸工作 |
| `main.py:243-304` vs `:306-360` | `_send_fake_event` 与 `_send_system_event` 大段重复 | 改 session/UMO 逻辑要改两处 |
| `tools/*.py` | `set_rcon`/`get_rcon` 三份复制 | 新增模块沿用复制，别急着抽象 |

---

## 提交约定

提交信息用中文，一个提交只做一件事，不混重构与功能。

历史提交是纯中文短句（`修复agent多轮工具调用时输出noresponse会被发送到mc的问题`、`新增事件上报`、
`更新readme`），没有 type 前缀也不用回头改。**新提交**按本项目个人约定写
`<type>(scope): <中文动词短语>`，不加句号，例如：

```
fix(tools): 修复模组物品被强加 minecraft: 前缀
feat(log): 新增玩家死亡事件上报
```

commit / push / PR 只在用户明确要求时执行。
