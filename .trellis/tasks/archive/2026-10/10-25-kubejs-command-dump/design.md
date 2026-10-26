# KubeJS 命令树导出技术设计

共享快照、发布、查询和优先级契约见父任务 `../10-25-mod-command-kb/design.md`。本文件只补充 KubeJS 主路径实现。

## 1. 脚本导出

- `assets/runtime_dump.js` 的 `researchdump` 执行体把 `ctx` 传入 dump 流程，在调用时获取活动 dispatcher，不使用注册事件的旧 dispatcher。
- 调用 `getAllUsage(root, ctx.source, false)` 获取全树；`restricted=false` 不执行 `requires` 可见性过滤。将 Java String 显式转为 JS String，再生成共享扁平 entries。这些是当前 dispatcher 已注册的完整 usage 路径，不代表当前 RCON/玩家必然可执行，实际执行仍受 `requires`、source 类型和执行体内部玩家检查限制。
- 普通行的 `name` 为首个空格前的根 literal，`syntax` 为完整行；redirect 行拆成普通 prefix + `redirect` 字段，不作为可执行路径。
- 所有条目先完整构建，再一次性 `JsonIO.write('runtime_dump/commands.json', ...)`；0 条或异常归入 `failed.commands`，不写空文件。
- `producer='kubejs'`、`kind='commands'`、`schema_version=1`，`count=entries.length`。
- `RD_VERSION` 升级为 `3`；DONE counts 增加 commands，四个注册表类别逻辑保持不变。

## 2. 发布与查询改造

在 `kb/commands.py` 内增加共享快照校验/发布能力，供本子任务导入和后续 RCON 生产者复用：

- 校验完整 JSON 和全部 entries，拒绝坏文件、空快照、错误 kind/version、count 不符及缺必要字段；`syntax == name` 是合法根级 usage，不得据此过滤条目。
- 对有效 entries 去重、稳定排序，写入数据目录临时文件后 `os.replace`；临时文件失败时清理，旧快照不动。
- 同机导入从 server_dir 读取原始 JSON，发布到 data_dir；只有 canonical 不存在时才兼容旧 JSONL。
- 查询按根聚合运行时 usage，与 vanilla 元数据合并；纯内置条目保留现有 `source/level`，运行时同根只继承 `desc/cat`，`level` 显示未知、`source=unknown`，不把内置默认权限或来源当作当前运行时验证结果。usage 搜索、redirect 展示和每根 8 条输出上限按父设计执行。
- 发布校验允许 `producer ∈ {kubejs, rcon}`；查询对 `producer="rcon"` 显示「语法来自 RCON help，深分支为压缩语法」的降级提示。含 KubeJS 运行时结果时统一显示一次「语法为当前 dispatcher 已注册路径，实际执行受权限与 source 限制」的能力边界说明，不与 RCON 提示混用。
- 命令快照每次查询重新读取已发布文件（或重建后立即失效），不做模块级缓存：`/mc_kb_dump` 后不重启插件也要看到新命令；`_load_vanilla` 的模块级缓存只适用于随插件分发的固定清单。

`KnowledgeBase.rebuild()` 将命令导入作为独立步骤：命令警告不阻断物品重建，物品失败也不撤销已发布命令快照。`kb/builder.py` 对 commands 文件直接跳过，不修改四类 dump 的字段和优先级。

## 3. 编排与文档

- `RuntimeDumpRunner._format_counts` 把 commands 单独成项展示，**不并入「共 N 条」的物品总数**（现有 `sum(counts.values())` 会把命令条目算进物品数）；总回执同时保留 failed 列表。
- `MANUAL_FALLBACK` 说明 `/mc_kb_rebuild` 会同时导入命令快照和重建物品库。
- README 更新 RD_VERSION、`commands.json` 跨机复制路径（仅迁移命令查询）、usage 能力边界、redirect 和旧缓存行为；明确完整物品迁移沿用现有流程，不在本期新增，物品 builder 仍要求有效的 `mc_server_dir` 和 `mods/`。
- 更新 `.trellis/spec/backend/runtime-dump.md` 的跨层契约，以及目录说明中 commands 的职责；不新增配置项。

## 4. 验证策略

- 新建 `tests/` 目录（标准库 `unittest`，`tests/test_*.py`）为命令快照/查询建立聚焦测试，用临时目录隔离，不引入 pytest 或新依赖；这些测试是离线回归证据，不替代真机验证。仓库此前没有测试目录，本任务是该约定的起点。
- 覆盖 canonical/legacy、同名多 usage、根级 limit、usage 关键词、vanilla 合并、redirect、原子替换、各类坏输入和 `producer=rcon` 降级显示；另覆盖仅根 usage（`foo`，`count=1`）、根与子 usage 并存（`foo` / `foo bar`，`count=2`）的 count、去重、排序和空快照判断，以及运行时权限元数据和 KubeJS 能力边界提示。
- 做 `compileall`、`node --check assets/runtime_dump.js`、`python3 -m unittest discover -s tests -v`，并按 AstrBot 根项目配置运行 `ruff format .` 和 `ruff check .`；不引入 pytest 或新运行时依赖。
- 在 CTI0.46 和 Farming 按已获授权做真实部署/reload/dump；记录两版本命令样本、counts、耗时和四类原 dump 回归。
- 真机一键闭环统一按以下顺序验收：临时移走数据目录旧 canonical；首轮只执行一次 `/mc_kb_dump`，由既有 `RuntimeDumpRunner` rebuild 回调接入 `KnowledgeBase.rebuild`，不得手工补跑 `/mc_kb_rebuild`；立即用 `search_mc_commands` 查到新增模组命令；核对四类旧 dump 与物品重建；再执行一次 `/mc_kb_dump` 验证幂等无重复。AstrBot 指令装饰/权限保持现状并做装配检查。

## 5. 回滚点

- 离线代码可按文件回滚；canonical 快照删除后即退回 vanilla/旧 JSONL。
- 服务器部署前备份既有 `kubejs/server_scripts/runtime_dump.js` 到临时位置；若新版脚本失败，恢复并 reload。runtime_dump 是派生数据，不备份世界或玩家数据。
- 若 Farming 由本任务启动，测试结束报告运行状态；不擅自执行 stop。
