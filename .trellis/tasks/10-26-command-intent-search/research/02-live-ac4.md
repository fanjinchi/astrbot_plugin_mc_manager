# AC4 真实模型复验证据（2026-10-28）

结论：**5/5 通过**（Farming 3/3、CTI 2/2）。每条中文意图都由真实 AstrBot provider + 真实模型完成，只在工具原始输出里核对目标根与完整 syntax，未执行任何 MC 命令。

## 1. 快照来源与发布

为避免影响正在运行的 CTI 原服，全部使用 P0 建立的隔离副本（KubeJS 保留）：

| 组 | 真实来源（隔离副本） | 原始版本 | 已发布路径 | producer | count | roots | SHA-256 |
|---|---|---|---|---|---|---|---|
| Farming | `/home/guigui/mc/rcon-help-probe/Farming-kubejs` | 1.20.1 Forge 47.4.20 | `/home/guigui/mc/ac4-roots/Farming/data/plugin_data/astrbot_plugin_mc_manager/runtime_dump/commands.json` | kubejs | 2248 | 193 | `d945b27c3d59927202a4da075be26db586e9cd342b60242cfa055a886c035db1` |
| CTI | `/home/guigui/mc/rcon-help-probe/CTI-kubejs` | 1.19.2 Forge 43.4.12 | `/home/guigui/mc/ac4-roots/CTI/data/plugin_data/astrbot_plugin_mc_manager/runtime_dump/commands.json` | kubejs | 2061 | 188 | `0749006dbcac9a06138cbacd2f3ca7b8fe9391fb9a3bd91a48ecdeeda80e6ce2` |

生成方式：生产链路 `runtime_dump.RuntimeDumpRunner.run()`（部署 `assets/runtime_dump.js` → RCON `researchdump` → 解析 `[rd] DONE`），发布走共享契约 `kb.commands.import_snapshot()`（`validate_snapshot()` + 原子 `publish_snapshot()`）。原始导出文件仍在副本的 `runtime_dump/commands.json`；副本已停服，原实例未被写入。

## 2. 独立 ASTRBOT_ROOT 与模型

| 项 | Farming 组 | CTI 组 |
|---|---|---|
| `ASTRBOT_ROOT` | `/home/guigui/mc/ac4-roots/Farming` | `/home/guigui/mc/ac4-roots/CTI` |
| 插件 data_dir（`StarTools.get_data_dir`） | `/home/guigui/mc/ac4-roots/Farming/data/plugin_data/astrbot_plugin_mc_manager` | `/home/guigui/mc/ac4-roots/CTI/data/plugin_data/astrbot_plugin_mc_manager` |
| 配置副本 SHA-256 | `71b02aa454f24d4ab5c2648207817725f897244fd1bea796e17936163a63c0b7` | `71b02aa454f24d4ab5c2648207817725f897244fd1bea796e17936163a63c0b7` |

- 配置副本来自生产 `data/cmd_config.json`，脱敏处理：清空 `platform`、`platform_settings`、`admins_id`，其余（provider / provider_sources / provider_settings）保留；两组同一份。
- provider：`deepseek/deepseek-v4-flash`（source `deepseek`，type `openai_chat_completion`）；model：`deepseek-v4-flash`；`custom_extra_body`：`{"temperature": 1, "max_tokens": 384000, "reasoning_effort": "max"}`。
- 无 provider/model fallback：harness 只构造这一个 provider，不传 fallback 列表。
- 工具集：用 AstrBot 自己的 `FunctionToolManager` 从 `main.py` 的真实 docstring 生成 schema，只注册 `search_mc_commands`；harness 断言 `len(func_list) == 1`，证据里 `tool_count=1`、`tool_name=search_mc_commands`、工具描述 SHA-256 `03414e905f94199f…`。
- 系统提示固定为：`你是一个 Minecraft 服务器管理助手。你可以使用提供的工具来查询信息。`；每条用例用全新 session id，无历史、无额外提示词。
- 工具实现是生产同一函数 `kb.commands.search_commands`，`data_dir` 由 `StarTools.get_data_dir("astrbot_plugin_mc_manager")` 在各自 ASTRBOT_ROOT 下解析。

## 3. 逐条结果

### Farming（1.20.1）

| # | 用户输入 | 实际 keyword(limit) | 目标根 | 目标 syntax | 工具轮数 |
|---|---|---|---|---|---|
| 1 | 把酒陈酿到 10 年 | wine(limit=8) / age(limit=8) / wine age years(limit=8) / wine info(limit=8) | 命中 | 全部出现 | 2 |
| 2 | 给 Steve 开启任务编辑模式 | quest editing(limit=8) / quest mode(limit=8) | 命中 | 全部出现 | 1 |
| 3 | 看看老王激活了哪些传送石碑 | waystone list player(limit=8) / waystones(limit=8) | 命中 | 全部出现 | 2 |

### CTI（1.19.2）

| # | 用户输入 | 实际 keyword(limit) | 目标根 | 目标 syntax | 工具轮数 |
|---|---|---|---|---|---|
| 1 | 清掉全服辐射 | radiation removeAll(limit=8) / radiation(limit=8) | 命中 | 全部出现 | 1 |
| 2 | 把 AE2 频道模式换一下 | channelmode(limit=8) / ae2 channel(limit=8) | 命中 | 全部出现 | 1 |

逐项目标 syntax：

- Farming：`wine age <years>` / `wine info`、`ftbquests editing_mode <enabled> <player>`、`waystones list <player> all`。
- CTI：`mek radiation removeAll`、`ae2 channelmode default|infinite|x2|x3|x4`（5 条全部出现在工具输出）。

完整、未截断的工具调用记录（keyword、limit、data_dir、原始输出、最终回答）见 `ac4-evidence-farming.json` 与 `ac4-evidence-cti.json`。

执行类工具调用：**0**（工具集只有 `search_mc_commands`，harness 不注册、不调用任何执行/消息/外部写入工具；全程无 MC 命令执行）。

## 4. 过程中发现的环境问题（重要）

**KubeJS `/reload` 会让部分模组命令从 dispatcher 消失。** 对照实验（CTI-kubejs 副本，同一进程）：

1. 重启后立即 `help ae2` → 正常返回 `/ae2 channelmode [infinite|default|x2|x3|x4]` 等子命令；
2. 执行一次 RCON `reload` 后再 `help ae2` → `Unknown command or insufficient permissions`。

对应后果：首次部署 `runtime_dump.js` 会触发 `/reload`，此时导出的快照会缺这些命令——同一副本首轮快照为 184 根 / 2038 条，重启后不 reload 再导出为 **188 根 / 2061 条**（本次 AC4 使用后者）。因此本次采用「重启副本 → 脚本已部署不再 reload → 导出」的顺序。

## 5. 边界与未覆盖

- harness 直接使用 AstrBot 的 provider 类与工具 schema，未经过完整的 `AstrMessageEvent` / 插件管线；等价性边界是「同一 provider 类 + 同一模型 + 同一工具 schema + 同一查询实现」。
- 只验证检索；不执行、不校验执行可行性（权限、玩家上下文、RCON 可见性另属执行层）。
- 单次运行，不代表模型在其他温度/其他 provider 下同样稳定；固定夹具见 `prd.md` AC2。
