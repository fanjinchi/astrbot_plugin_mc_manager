# LLM 工具精简与原版命令知识库

## 背景与决策（已与用户确认）

插件注册了 30 个 llm_tool，其中 26 个是 MC 命令薄封装，与通用工具 execute_command 功能重叠，
schema 占用 token 且拉低工具选择准确率。execute_script（插件内 exec Python）已在本会话删除
（安全：exec 全量 builtins + admin_ids 为空时全员放行 = 进程级 RCE；多步任务由 AstrBot 电脑使用能力承接）。

用户在会话中确认的决策：

1. 工具从 28 精简到 12（删 17 个低频薄封装 + 新增 1 个命令知识库查询工具）。
2. whitelist/banlist 本质是管理员功能（游戏内 3 级权限），其查询工具一并收回——直接删除，
   管理员要查看走 execute_command。免权限只读只保留 list_players / search_mc_items / search_mc_commands。
3. 有中文映射但低频的工具（set_difficulty / set_gamerule / title 等）也删除，不保留。
4. 保留通用 execute_command（含危险命令拦截）。
5. 建立原版 MC 命令的内置固定知识库，让 LLM 调 execute_command 前能查到命令用法；
   mod 命令由 issue #5 后续通过 runtime dump 并入。

## 保留的 12 个工具

免权限只读：list_players、search_mc_items、search_mc_commands（新）
管理员：give_item、summon_entity（均有 normalize_mc_id 模组 ID 处理）、teleport_player、
set_gamemode、set_weather、set_time（高频+中文映射）、tellraw（聊天桥出口）、
send_to_qq_group（插件独有）、execute_command（通用兜底）

## 删除的 17 个 llm_tool

kick_player、ban_player、pardon_player、op_player、deop_player、whitelist_add、whitelist_remove、
kill_entity、clear_inventory、set_experience、say_message、title、save_world、whitelist_list、
banlist、set_difficulty、set_gamerule

连带清理 tools/ 模块内从未注册的死代码：stop_server、get_server_status、whitelist_on/off、
reload_whitelist、add_time、fill_blocks、set_spawn。player_tools.py 清空后整个文件删除。

## 原版命令知识库设计

- 数据：assets/vanilla_commands.json 随插件分发（固定数据，非派生缓存，不进 items.db）。
  字段：name / syntax / desc(中文) / level(游戏内权限等级) / cat(分类)。
- 查询：kb/commands.py 独立模块，按 名称/描述 模糊匹配，启动时加载 JSON；
  若数据目录存在 runtime_dump/commands.jsonl（issue #5 未来的 mod 命令导出）则合并。
- 工具：search_mc_commands(keyword, limit) 免权限只读，不依赖 mc_server_dir 配置。
- execute_command 的 docstring 加一句指引：不确定命令用法时先 search_mc_commands。

## 验收标准

- [ ] main.py 仅剩 12 个 @filter.llm_tool，py_compile 通过，无残留引用
- [ ] search_mc_commands 在无 mc_server_dir 配置时也能返回原版命令用法
- [ ] README 功能清单/权限分级与代码一致
- [ ] 被删工具对应的 tools/ 模块函数一并删除，无死代码

## 范围外

- mod 命令的 runtime dump 导出与合并逻辑细节（issue #5，本任务只留合并入口）
- 提交 commit（用户自行决定）
