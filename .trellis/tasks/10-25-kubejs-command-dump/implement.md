# KubeJS 命令树导出执行计划

## 前置状态

- 父任务与需求边界已确认；本任务依赖的 API 调研见 `research/01-kubejs-api.md`。
- CTI0.46 与 Farming 均已获部署/reload/启动实测授权。
- 开始实施前运行 `task.py start .trellis/tasks/10-25-kubejs-command-dump`，父任务保持 planning 总控。

## 实施清单

- [x] 1. 新建 `tests/`（标准库 unittest）并固定共享 schema 夹具：普通多 usage、仅根 usage（`foo`，`count=1`）、根与子 usage 并存（`foo` / `foo bar`，`count=2`）、redirect、vanilla 同根、legacy JSONL、坏 JSON、空 entries、count 不符、运行时权限元数据、KubeJS 能力边界与 `producer=rcon` 降级显示；验证去重、排序及合法 `syntax == name` 不被过滤。
- [x] 2. 在 `kb/commands.py` 实现 canonical 校验、去重排序、原子发布和读取；保留无快照时 vanilla 行为及旧 JSONL 兼容，不过滤合法根级 `syntax == name`。
- [x] 3. 将命令导入接入 `KnowledgeBase.rebuild()`，隔离物品/命令故障；让 `kb/builder.py` 忽略 commands 文件，避免物品统计和 hint 副作用。
- [x] 4. 修改 `assets/runtime_dump.js`：执行时取活动 dispatcher，`restricted=false` 全树导出，写 `commands.json`，升级 RD_VERSION=3，counts/failed 增加 commands。
- [x] 5. 更新 `RuntimeDumpRunner` 数量回执（commands 单独成项、不并入物品「共 N 条」）和手工提示；不修改现有 RCON 超时、重试和 rebuild 回调签名。
- [x] 6. 完成查询聚合：根级 limit、多 usage 搜索、每根 8 条展示上限、redirect 提示、unknown/null 格式、`producer=rcon` 降级提示及 KubeJS 已注册路径能力边界说明；纯内置条目保留现有 `source/level`，运行时同根只继承 `desc/cat`，`level` 显示未知、`source=unknown`；快照不做进程级缓存。
- [x] 7. 更新 README、`runtime-dump.md` 和必要目录 spec；说明跨机复制 `commands.json` 仅迁移命令查询，完整物品迁移沿用现有流程且不在本期新增；检查 `search_mc_commands` 的工具描述仍准确，不新增配置或语义功能。

## 离线验证

```bash
python3 -m compileall -q main.py rcon_client.py runtime_dump.py tools/ kb/ tests/
node --check assets/runtime_dump.js
python3 -m unittest discover -s tests -v
ruff format .      # 见下方偏差说明
ruff check .       # 见下方偏差说明
```

- [x] 新建的 `tests/` 通过（31 个用例）；不引入 pytest 或新运行时依赖。
- [x] 所有新离线夹具通过，特别验证无效新文件不会替换旧快照。
- [x] 检查 git diff，确认没有物品字段、危险命令权限或无关重构变化。
- [ ] `ruff format .` / `ruff check .` 全仓通过——**未达成，见偏差说明，需要用户决策**。

## 偏差说明（2026-10-26）

1. **ruff 无法全仓通过**：仓库既有代码未按 AstrBot 根项目 `pyproject.toml` 格式化——
   `ruff format --check .` 报 36 个文件需重排，`ruff check .` 报 383 个既有错误。全仓 reformat 会产生
   与本期无关的大 diff，违反「不扩张范围」。实际做法：`kb/commands.py`（本期重写）与 `tests/*.py`（新增）
   已 `ruff format`；既有文件不整文件 reformat，只保证不新增错误类型。剩余告警均为仓库既有风格规则
   UP031（`%` 格式化）与 UP045（`Optional`），与相邻代码一致。
   如需彻底干净，需要单独的「全仓 ruff 基线」任务。
2. **真机验证未执行**：本会话文件沙箱为 workspace-write，`/home/guigui/mc/CTI0.46` 与 AstrBot
   `plugin_data` 均为只读挂载；部署脚本、`/reload`、发布快照都需要一次沙箱升级批准，会话期间
   未获批准（两次审批请求均超时）。已准备脚本 `verify_live.py`，批准后一条命令即可跑完整链路。

## 离线证据（2026-10-26）

- `tests/test_commands.py`：快照校验/去重排序/原子发布失败保留旧快照/导入 missing-published-invalid/
  legacy JSONL 仅无 canonical 时读取/根合并只继承 desc-cat/仅根与根+子 usage/redirect 提示/
  limit 按根计数/8 条展示上限/`producer=rcon` 降级提示/坏快照告警/物品重建失败仍保留命令快照。
- `tests/test_runtime_dump.py`：`_format_counts` 命令条目不并入物品总数、`_parse_dump_summary` 带 commands、
  `_load_runtime_dumps` 跳过 `commands.json` 且物品 dump 仍加载。
- `tests/test_dump_script.py` + `tests/js_dump_harness.js`：用 Node 桩执行真实 `assets/runtime_dump.js`——
  五类产物落盘、RD_VERSION=3、commands 条目过 Python 契约校验、5 种 usage 形态（含 redirect 拆分）、
  dispatcher 抛错时只把 commands 记入 failed 且不影响四类物品 dump。
- Brigadier 格式实测：本地 javap + 最小 Java 程序，1.0.18（CTI）与 1.1.8（Farming）输出一致：
  `foo` / `foo bar` / `foo <count>` / `alias -> foo` / `loop ...`。

## 评审与修复（2026-10-26，第二轮）

两个独立子代理（spec/standards 轴 + 正确性/回归轴，均为 fresh context、只读）评审后，
共同指出 1 个 P0 与若干 P2；主会话逐条复现确认后修复：

- **P0（已修）**：快照存在后中文描述搜索整体失效。`getAllUsage` 覆盖整棵 dispatcher ⇒ 快照含全部原版根 ⇒
  内置行被同根跳过，而 `_score_runtime` 不匹配继承来的 `desc`。已在 `_score_runtime` 加入 desc 匹配，
  并补回归用例；顺带修正快照存在时仍提示"模组命令需导出"的误导文案。
- **P2（已修）**：外部 dispatcher root 的 `prefix ->` 按 redirect 标记（JS + harness 夹具）；
  0 字节 `commands.json` 不再进物品告警（跳过提前到空文件检查之前）；
  原子发布改用 `tempfile.mkstemp` 唯一临时名；物品重建失败时命令快照告警进回执；
  补 8 条 usage 上限、发布失败 status=error、合并根按中文 desc 搜索、快照存在时无结果文案等用例。
- **文档（已修）**：`runtime-dump.md` 签名表行号按实测更新、补充命令树导出与外部 root redirect 契约；
  README 的 RCON fallback 标注"尚未实现"；父 design 的"空描述"改为占位描述；quality-guidelines 的 lint 措辞与偏差说明对齐。
- **转出（不在本子任务）**：模组命令"中文描述"能力缺口与 4 条候选路线，已写入
  `../10-25-mod-command-kb/mod-command-chinese-brief.md`，交新 PRD 会话 grill。
- 离线用例：31 → 38，全部通过。
- **第三轮（修复复核）**：独立子代理复核结论"可接受，无 P0/P1"，P0/P2 修复全部成立（含变异实验证明用例有效），
  仅剩 2 处 P2 已收：`runtime-dump.md` 行号 238→242、150→150-153；权限显示文案按"全量快照下原版根被覆盖、
  权限显示未知"修正（README + `search_mc_commands` 描述），并在 spec 标注 `_trigger`/`execute_async` 用例为待补。

## 真机验证（已授权，待沙箱批准）

- [ ] CTI0.46 / 1.19.2：备份现有部署脚本并临时移走数据目录旧 canonical；首轮只执行一次 `/mc_kb_dump`，不得手工补跑 `/mc_kb_rebuild`；由既有 RuntimeDumpRunner rebuild 回调完成发布/重建，立即验证 `researchdump`、`execute` 多分支可通过 `search_mc_commands` 查询，DONE 含 commands，四类原 dump 与物品重建不回归；再执行一次 `/mc_kb_dump` 验证幂等无重复。
- [ ] Farming / 1.20.1：记录初始状态并按现有启动方式启动，部署/reload/触发；验证 `wine info`、`wine age <years>` 可查，redirect 不被当作完整命令。
- [ ] 在两实例测试坏/旧快照保留和重复 dump 幂等；记录 counts、文件大小、耗时、failed 和查询样例。
- [ ] 汇总真机证据；Farming 若原本停止，不擅自 stop，报告最终运行状态。

执行入口（一次命令，需要 danger-full-access 批准）：

```bash
/home/guigui/code/AstrBot/.venv/bin/python \
  .trellis/tasks/10-25-kubejs-command-dump/verify_live.py \
  --server-dir /home/guigui/mc/CTI0.46 \
  --data-dir /home/guigui/code/AstrBot/data/plugin_data/astrbot_plugin_mc_manager
```

注意：AstrBot 里跑的还是旧版插件代码，真机验证前需要重载插件/重启 AstrBot 才能加载本期 Python 改动。

## Review / Finish gates

- [ ] 对照父 AC1–AC5 和本子任务全部 AC；任何未实测项明确保留，不宣称完成。
- [ ] 分派独立 spec/standards review 与 `trellis-check`，问题回原分支修复。
- [x] 将稳定的新契约更新到 `.trellis/spec/backend/`：把 quality-guidelines 里「本项目没有测试套件」改为 `tests/` 用标准库 unittest，并修正「没有 lint 配置」的过时表述以反映 AstrBot 根项目 ruff 配置；commit 仅在有明确用户要求时执行。
- [ ] 子任务验收后归档，再允许父任务启动 RCON fallback。

## Rollback points

- 步骤 2–3 后：可单独回滚 Python 发布/查询，不影响脚本现状。
- 步骤 4 后：恢复 assets 与服务器部署脚本，reload 后回到 RD_VERSION=2；删除 commands 快照即可恢复旧查询。
- 真机异常：恢复部署前脚本备份并 reload；不触碰世界数据，不重复执行超时中的 RCON 命令。
