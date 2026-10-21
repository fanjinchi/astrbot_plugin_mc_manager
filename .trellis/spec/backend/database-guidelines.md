# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

**本项目没有数据库。** 没有 ORM、没有迁移、没有 SQL、没有本地 json/state 文件。

这不是遗漏，而是架构选择：MC 服务器的状态天然存在服务器自己的文件里，插件只是通过 RCON 发命令去改它；
插件自己的配置存在 AstrBot 配置系统里。新增任何"要持久化"的需求前，先按下表找现成落点。

| 需要的状态 | 现实存放位置 | 插件怎么读写 |
|---|---|---|
| 白名单 / OP / 封禁 | MC 服务器的 `whitelist.json`、`ops.json`、`banned-players.json` | 只发 `whitelist add`、`op`、`ban` 等命令（`tools/player_tools.py`），**不直接改文件** |
| 世界数据 | MC 服务器 `world/` 目录 | `save-all`（`tools/server_tools.py:149-158`） |
| 插件配置（RCON 地址、管理员、各类开关） | AstrBot 配置系统，schema 在 `_conf_schema.json` | 启动时 `self.config.get("key", default)`，只读 |
| 运行态（在线脚本、日志连接、重连计数） | 进程内存 | 实例/模块属性，如 `ScriptExecutor.running_scripts`（`script_executor.py:18`） |
| 对话上下文 | AstrBot 的 LTM / 事件管线 | 用 `StarTools.create_event` 投递事件（`main.py:272-276`），插件自己不存 |

---

## Query Patterns

不适用（无查询层）。等价约定：

- **读状态用命令，不用文件。** 想知道谁在线就 `list`（`tools/server_tools.py:39-48`），想知道白名单就
  `whitelist list`（`:161-170`），不要 `open("whitelist.json")`。
- **解析文本响应时**，解析逻辑放在调用侧并做兜底。范例：`rcon_client.py:104-132` 对 `list` 响应的解析
  （含格式不符时返回 `(0, [])`），但该函数目前是死代码，见 quality-guidelines "已知债务"。
- **批量操作** 用一条命令的目标选择器（`@a`、`@e[type=zombie]`），不要循环发 RCON；一批操作超过 2-3 条
  命令就写脚本走 `execute_script`（`script_executor.py`）。

---

## Migrations

不适用。

- 配置演化靠 `_conf_schema.json` + `config.get(key, default)` 的默认值兼容旧配置，没有迁移脚本。
- 移除历史配置项时保留注释说明（范例：`main.py:46-47` 记录"唤醒词配置已移除"），不要静默删读取。

---

## Naming Conventions

- 配置 key：`snake_case`，按域前缀分组（`rcon_*`、`log_*`、`enable_*`），见 `_conf_schema.json`。
- 内存态属性：`snake_case`；集合用 `set` / 带类型的 `dict`（`self.admin_ids`、`self.tools`）。

---

## Common Mistakes

- 为了"省事"新增 sqlite 或 `data.json`。本书已确认的部署形态是单服务器、单插件进程、状态在 MC 侧，
  加持久化只会引入双份真相和迁移负担。
- 直接在插件里读写 MC 的 `whitelist.json`：服务器运行中有内存态，改文件会被覆盖（要 `whitelist reload`）。
- 把管理员列表、RCON 密码写进代码常量。必须走 `_conf_schema.json` + `config.get`。
- 以为 `terminate()` 会落盘状态——它只断开日志连接（`main.py:338-343`）。
