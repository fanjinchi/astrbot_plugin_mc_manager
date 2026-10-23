# Directory Structure

> How backend code is organized in this project.

---

## Overview

这是一个 AstrBot 插件（单个 Python 包，没有 `src/` 布局，除 `tools/` 外无子包）。它不做 Web 服务，也
不跑数据库；"后端"就是 AstrBot 进程里的插件类 + RCON 通道 + 一条独立的日志监控链路。

代码分三层，依赖方向单向：

```
main.py                  插件入口（唯一 @register 的 Star 子类）
 ├─→ tools/*.py          纯 RCON 命令层：不 import astrbot，不打日志
 ├─→ rcon_client.py      RCON 异步长连接封装
 ├─→ log_client.py       日志监控客户端（TCP + 心跳 + 日志行解析）
 └─→ script_executor.py  LLM 生成 Python 脚本的执行器

log_server.py            独立脚本，部署在 MC 服务器那台机器上，禁止 import astrbot
```

---

## Directory Layout

```
astrbot_plugin_mc_manager/
├── main.py                 # Star 子类 MCManagerPlugin：全部 @filter.llm_tool / @filter.command、事件钩子、消息中转
├── rcon_client.py          # MinecraftRCON：长连接、重试、连接测试
├── log_client.py           # LogClient：连日志服务器、心跳、把日志行解析成回调
├── log_server.py           # LogServer：tail latest.log → 广播；独立进程运行
├── script_executor.py      # ScriptExecutor：exec 脚本、捕获 print、超时取消
├── tools/
│   ├── __init__.py         # 显式导出四个子模块（不用星号导入）
│   ├── id_utils.py         # normalize_mc_id()：资源 ID 归一化（无命名空间才补 minecraft:）
│   ├── player_tools.py     # kick / ban / pardon / op / deop / whitelist
│   ├── game_tools.py       # give / tp / gamemode / kill / clear / xp
│   ├── server_tools.py     # list / say / tellraw / title / save / banlist / execute_command + 危险命令开关
│   └── world_tools.py      # weather / time / difficulty / gamerule / summon / fill / setspawn
├── kb/                     # 物品知识库（mods/*.jar 的派生缓存，可整体删除重建）
│   ├── __init__.py         # KnowledgeBase 门面：rebuild / search / status
│   ├── scanner.py          # 离线扫 mods/*.jar + kubejs/：ID、中英文名、mod 归属
│   ├── vanilla.py          # 原版：en_us 取 ID/英文名，zh_cn 按优先级取；方块能否 give
│   ├── cfpa.py             # CFPA 汉化包：按版本选包、下载（GitHub→BMCLAPI）、md5 校验、解析
│   ├── builder.py          # 编排扫描→原版→CFPA→自定义→dump→落库→统计
│   ├── store.py            # SQLite schema + 读写（每次操作各自连接）
│   └── query.py            # 查询/回执/状态的对外文案
├── assets/
│   ├── runtime_dump.js         # KubeJS 运行时注册表导出脚本（可选增强）
│   └── extract_runtime_dump.py # 日志里的 ##RD## 行 -> runtime_dump/*.jsonl
├── _conf_schema.json       # AstrBot WebUI 配置 schema（配置项唯一来源）
├── metadata.yaml           # 插件元信息（name/desc/author/version/repo）
├── requirements.txt        # 运行时依赖，目前只有 aio-mc-rcon
└── README.md
```

---

## Module Organization

### 三层职责（不要打破）

1. **`tools/*.py` = 纯命令层。** 只做参数归一化、拼 MC 命令、调 `rcon.execute_async()`、把结果包装成中文
   字符串。不 import `astrbot`，不 `print`，不打日志。原因：这些函数同时被 `@filter.llm_tool` 和
   `ScriptExecutor` 直接调用，保持无框架依赖才能两边复用（见 `main.py:111-147` 的注册）。
2. **`main.py` = 唯一装配层。** `@filter.llm_tool` / `@filter.command` / `@filter.on_*` 只出现在这里。
   `tool_xxx` 方法只做两件事：权限检查 + 转发给 `tools`，实现一律下沉（参考 `main.py:508-519`）。
3. **基础设施 = 类 + 回调。** `MinecraftRCON` / `LogClient` / `ScriptExecutor` 都是普通类；跨模块依赖用
   注入：RCON 客户端通过模块级全局 `_rcon` 注入（`tools/game_tools.py:13-26`），由
   `main.py:103-109` 的 `_inject_rcon()` 统一调用。`LogClient` 用 `set_<x>_callback()` 注入
   （`log_client.py:401-482`），回调实现放在 `main.py` 的 `_on_*` 方法里。

### 新功能放哪里

| 要做的事 | 改哪里 |
|---|---|
| 新增一条 MC 命令能力 | `tools/` 最接近的模块加 `async def`，再在 `main.py` 包一层 `@filter.llm_tool` |
| 新增一个 LLM 工具 | `main.py` 的 `tool_*`；实现下沉到 `tools/` |
| 新增知识库能力（扫新来源/新查询） | `kb/` 对应模块；装配仍只在 `main.py` |
| 新增配置项 | `_conf_schema.json` + `main.py.__init__` 里 `self.config.get(...)` |
| 新增 MC 日志事件 | `log_client.py` 加 `*_PATTERN` 常量 + 回调字段 + `set_*_callback` + `_process_log_line` 分支；`main.py` 加 `_on_*` 并用 `_send_system_event` 上报 |
| 新增对外指令 | `main.py` 的 `@filter.command`（`test_connection`、`test_log` 是范例） |

### 一个"新增 RCON 工具"的完整改动清单

四步，缺一步 LLM 或脚本就用不上：

1. `tools/<模块>.py` 加 `async def xxx(...) -> str`，docstring 按 LLM 工具格式写（见 quality-guidelines）。
2. `main.py` 加 `@filter.llm_tool(name="xxx")` 的 `tool_xxx`：先 `_check_permission`，再 `await tools.xxx(...)`。
3. `main.py:_register_script_tools()` 里 `register_tool("xxx", ...)`（允许脚本调用时）。
4. `main.py:tool_list_script_tools` 的 `categories` 里归组（同上，否则列表里看不到）。

---

## Naming Conventions

- **文件**：`snake_case.py`；`tools/` 下统一 `*_tools.py`。
- **类**：PascalCase，直白领域名（`MinecraftRCON`、`LogClient`、`ScriptExecutor`）。
- **工具三处同名**：装饰器 `name`、`main.py` 方法 `tool_<name>`、`tools` 函数名完全一致
  （`give_item` / `tool_give_item` / `give_item`）。
- **回调**：构造侧 `set_<x>_callback()`，消费侧 `_on_<x>`。
- **常量**：模块级全大写下划线（`CHAT_PATTERN`、`DEATH_KEYWORDS`、`HEARTBEAT_TIMEOUT`）；
  一次性的危险命令清单写在函数内局部变量（`tools/server_tools.py:206`）。
- **私有成员**：单下划线（`_inject_rcon`、`_client`、`_process_log_line`）。

---

## Examples

- 纯命令层最佳范例：`tools/player_tools.py`（最短：注入 + 拼命令 + 返回中文结果）。
- 参数归一化范例：`tools/game_tools.py:72-99`（中文/数字 → 英文 gamemode 映射后校验）。
- 装配层范例：`main.py:508-519`（权限 → 转发的两行结构）。
- 回调 + 事件上报范例：`main.py:168-220`（`_on_player_join` 等）。

## 反例（本项目明确不这么做）

- 不新增顶层包或 `src/` 布局；插件目录本身就是一个包。
- 不在 `tools/` 或 `log_server.py` 里 import `astrbot`。
- 不为单条命令新建模块，先并入现有四类；真的成体系再开 `xxx_tools.py`。
- 不在 `main.py` 里直接拼 MC 命令发 RCON（例外：纯 UI 的 `_send_single_mc_message`，`main.py:449-466`）。
