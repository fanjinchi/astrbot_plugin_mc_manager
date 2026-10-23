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
 ├─→ log_watcher.py      本地日志监听器：轮询 mc_server_dir/logs/latest.log（要求同机）
 └─→ text_outbound.py    RCON 出站文本纯函数：tellraw 拼接 + 1460B 字节预算切段
```

> 2026-10 重构：旧的「log_server.py（MC 机独立脚本）+ log_client.py（TCP 客户端）」双进程通道已删除，
> 改为插件内 LogWatcher 直读本地日志。AstrBot 与 MC 服务端不同机时聊天互通不可用（有意放弃）。

---

## Directory Layout

```
astrbot_plugin_mc_manager/
├── main.py                 # Star 子类 MCManagerPlugin：全部 @filter.llm_tool / @filter.command、事件钩子、消息中转
├── rcon_client.py          # MinecraftRCON：长连接、重试、连接测试
├── log_watcher.py          # LogWatcher：轮询本地 latest.log、轮转检测、把日志行解析成回调
├── text_outbound.py        # tellraw 命令构造 + UTF-8 字节预算切段（纯函数，可独立测试）
├── tools/
│   ├── __init__.py         # 显式导出三个子模块（不用星号导入）
│   ├── id_utils.py         # normalize_mc_id()：资源 ID 归一化（无命名空间才补 minecraft:）
│   ├── game_tools.py       # give / tp / gamemode
│   ├── server_tools.py     # list / tellraw / execute_command + 危险命令开关
│   └── world_tools.py      # weather / time / summon
├── kb/                     # 物品知识库（mods/*.jar 的派生缓存，可整体删除重建）
│   ├── __init__.py         # KnowledgeBase 门面：rebuild / search / status
│   ├── scanner.py          # 离线扫 mods/*.jar + kubejs/：ID、中英文名、mod 归属
│   ├── vanilla.py          # 原版：en_us 取 ID/英文名，zh_cn 按优先级取；方块能否 give
│   ├── cfpa.py             # CFPA 汉化包：按版本选包、下载（GitHub→BMCLAPI）、md5 校验、解析
│   ├── builder.py          # 编排扫描→原版→CFPA→自定义→dump→落库→统计
│   ├── store.py            # SQLite schema + 读写（每次操作各自连接）
│   ├── query.py            # 查询/回执/状态的对外文案
│   └── commands.py         # 命令知识库查询：原版内置清单 + 可选模组导出合并（与物品库无配置依赖）
├── assets/
│   ├── vanilla_commands.json   # 原版命令固定知识库（随插件分发，非派生缓存）
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
   字符串。不 import `astrbot`，不 `print`，不打日志。原因：保持无框架依赖，便于脱离 AstrBot 独立测试与复用
   （历史上的 ScriptExecutor 复用前提已随脚本执行器删除而消失）。
2. **`main.py` = 唯一装配层。** `@filter.llm_tool` / `@filter.command` / `@filter.on_*` 只出现在这里。
   `tool_xxx` 方法只做两件事：权限检查 + 转发给 `tools`，实现一律下沉（参考 `main.py:487-499`）。
3. **基础设施 = 类 + 回调。** `MinecraftRCON` / `LogWatcher` 都是普通类；跨模块依赖用
   注入：RCON 客户端通过模块级全局 `_rcon` 注入（`tools/game_tools.py:13-26`），由
   `main.py:124` 的 `_inject_rcon()` 统一调用。`LogWatcher` 用 `set_<x>_callback()` 注入
   （`log_watcher.py:175-191`），回调实现放在 `main.py` 的 `_on_*` 方法里。

### 新功能放哪里

| 要做的事 | 改哪里 |
|---|---|
| 新增一条 MC 命令能力 | `tools/` 最接近的模块加 `async def`，再在 `main.py` 包一层 `@filter.llm_tool` |
| 新增一个 LLM 工具 | `main.py` 的 `tool_*`；实现下沉到 `tools/` |
| 新增知识库能力（扫新来源/新查询） | `kb/` 对应模块；装配仍只在 `main.py` |
| 新增配置项 | `_conf_schema.json` + `main.py.__init__` 里 `self.config.get(...)` |
| 新增 MC 日志事件 | `log_watcher.py` 加 `*_PATTERN` 常量 + 回调字段 + `set_*_callback` + `_process_log_line` 分支；`main.py` 加 `_on_*`，按需 `_forward_to_bound_group` / `_send_system_event` 上报 |
| 新增对外指令 | `main.py` 的 `@filter.command`（`test_connection`、`test_log` 是范例） |

### 一个"新增 RCON 工具"的完整改动清单

两步：

1. `tools/<模块>.py` 加 `async def xxx(...) -> str`，docstring 按 LLM 工具格式写（见 quality-guidelines）。
2. `main.py` 加 `@filter.llm_tool(name="xxx")` 的 `tool_xxx`：先 `_check_permission`，再 `await tools.xxx(...)`。

注意：插件刻意只保留少量高价值专用工具（12 个）。低频命令**不新增专用工具**，由 `execute_command`
通用工具兜底，LLM 通过 `search_mc_commands` 查用法。新增专用工具前先确认它足够高频或带有
execute_command 替代不了的附加逻辑（中文映射、ID 归一化、权限粒度）。

---

## Naming Conventions

- **文件**：`snake_case.py`；`tools/` 下统一 `*_tools.py`。
- **类**：PascalCase，直白领域名（`MinecraftRCON`、`LogWatcher`、`KnowledgeBase`）。
- **工具三处同名**：装饰器 `name`、`main.py` 方法 `tool_<name>`、`tools` 函数名完全一致
  （`give_item` / `tool_give_item` / `give_item`）。
- **回调**：构造侧 `set_<x>_callback()`，消费侧 `_on_<x>`。
- **常量**：模块级全大写下划线（`CHAT_PATTERN`、`DEATH_KEYWORDS`、`DEATH_PATTERN`）；
  一次性的危险命令清单写在函数内局部变量（`tools/server_tools.py` 的 `execute_command` 内）。
- **私有成员**：单下划线（`_inject_rcon`、`_client`、`_process_log_line`）。

---

## Examples

- 纯命令层最佳范例：`tools/game_tools.py`（注入 + 参数归一化 + 拼命令 + 返回中文结果）。
- 参数归一化范例：`tools/game_tools.py:72-99`（中文/数字 → 英文 gamemode 映射后校验）。
- 装配层范例：`main.py:487-499`（权限 → 转发的两行结构）。
- 回调 + 事件上报范例：`main.py:193-241`（`_on_player_join` 等）。

## 反例（本项目明确不这么做）

- 不新增顶层包或 `src/` 布局；插件目录本身就是一个包。
- 不在 `tools/` 或 `text_outbound.py` 里 import `astrbot`（`log_watcher.py` 只用 astrbot 的 logger）。
- 不为单条命令新建模块，先并入现有四类；真的成体系再开 `xxx_tools.py`。
- 不在 `main.py` 里直接拼 MC 命令发 RCON（例外：聊天出站文本统一走 `text_outbound.py` 纯函数构建 tellraw，`main.py` 只负责调用）。
