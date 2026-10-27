# 模组命令英文意图检索改进

## Goal

让调用方 LLM 能把中文用户意图提炼为简洁的英文概念词，并通过现有 `search_mc_commands` 召回真实命令快照中的正确根命令与相关 usage。只改进调用引导和现有关键词匹配，不建设自动中文描述或语义映射系统。

## Background and Dependency

- 父任务：`.trellis/tasks/10-25-mod-command-kb`；讨论输入：`.trellis/tasks/10-25-mod-command-kb/mod-command-chinese-brief.md`；调研证据：`research/01-intent-retrieval.md`。
- 代码依赖 `.trellis/tasks/archive/2026-10/10-25-kubejs-command-dump/` 已完成：本任务复用其快照 schema、发布与查询实现，不与产品代码并发施工。
- **2026-10-26 启动口径**：本任务保持 PRD-only。代码依赖已具备，可先 `task.py start` 做 AC1–AC3/AC5 的离线实现与回归；这只是启动许可，不是完成/归档许可。
- **AC4 真实快照当前缺口**：Farming 与 CTI 的两份真实 `commands.json` 当前均不存在，是归档验收流程清理验证产物/临时发布目录所致，不是子任务一未完成。开始 AC4 前必须重新生成两份快照，分别经共享发布流程导入两个独立 `ASTRBOT_ROOT` 下的测试数据目录；历史 count/root 数不能替代新文件、SHA-256 和逐项 syntax。AC4 的同一实际 AstrBot Agent/provider/model 5/5 全部通过前，本任务不得完成或归档。
- 本任务与 `.trellis/tasks/10-25-rcon-help-command-fallback` 的传输采集无关；查询改进应对两种 producer 一视同仁。
- 当前 `main.py` 的 `search_mc_commands` 由调用方 LLM 提供单个 `keyword`；`kb/commands.py` 对名称、usage、desc 和 redirect 做整串小写包含匹配。
- 已确认 Brigadier/KubeJS/RCON help 均不提供统一命令描述。部分模组有官方英文命令文档，但没有统一完整的中英文说明来源；真实 dispatcher usage 仍是语法权威。
- 2026-10-26 的离线临时原型使用 19 个根、49 条 usage 夹具：中文关键词未召回目标模组命令，合理英文单 token 对 5 条代表意图均召回目标根与目标 usage；多词整串查询出现 7/7 漏检，token-AND 原型在其 8 个扩展查询中挽回 6 个。
- 原型是非盲、小规模夹具，不是实际 AstrBot 模型或真实全量快照的端到端证据；不得据此声称所有模组、所有模型都无需中文资料。

## Requirements

- **R1 调用引导**：调整 `search_mc_commands` 的工具说明和无结果提示。中文意图用于模组命令时，引导调用方先提炼一个或多个简短英文根名、子命令或参数概念词，不直接发送整句中文；未命中时尝试更短 token 或英文同义表达，命中根后再用子命令/参数词细化。保留现有原版中文描述搜索能力，不宣称工具自身支持模组中文语义搜索。
- **R2 归一化与 token AND**：查询先转小写，按空白、下划线和连字符拆分 token，连续分隔符不产生空 token；`->` 是 redirect 结构标记，例外保留，不得按普通连字符拆没。token 与名称、usage、desc、redirect 比较时忽略空白、下划线和连字符，因此 `channel mode`、`channel_mode`、`channel-mode`、`channelmode` 必须能命中同一 `channelmode` usage。所有 token 采用无序 AND：每个 token 至少命中该根的一个现有可搜索字段才返回；普通 usage 要进入优先展示的 `matched`，必须由同一 usage 覆盖全部查询 token。
- **R3 排名与结构边界**：token 使用小写子串匹配，以兼容 `quest`/`ftbquests`、`waystone`/`waystones`；不引入自动翻译、同义词扩展、词干分析、拼写纠错、拼音、正则或模糊语义打分。精确根名和根名前缀排名使用忽略空白/`_`/`-` 后的完整查询与根名比较，例如 `botania-skyblock`、`botania_skyblock`、`botania skyblock`、`botaniaskyblock` 均按同一精确根处理；保留精确根、前缀、包含、其他内容的现有优先级和按根计数的 `limit`。redirect target 参与根级 AND；`alias target` 与 `alias -> target` 均应召回对应 redirect，显式 `->` 只匹配 redirect 结构，单独查询 `->` 保留现有重定向搜索能力。redirect 继续只作别名提示，不进入普通 `matched` usage，也不变成可执行路径。
- **R4 输出与回归**：单 token 查询、原版中文 desc 搜索、redirect、坏快照处理及 producer 提示不得回归。单根最多 8 条 usage 的上限保持不变；多词命中的相关 usage 必须优先于同根其他 usage，不为根名查询无差别展开全部 usage。
- **R5 安全边界**：本任务只验证检索和候选用法，不自动执行搜索到的 MC 命令，不根据英文名称伪造中文说明、modid、权限、参数可选性或来源。真实复验必须按 AC4 做工具白名单或执行工具拦截，不得仅依赖提示词约束，不得执行清辐射、改模式、编辑任务等有状态命令。
- **R6 最小实现与文档**：不新增运行时依赖、配置项、快照字段或存储层。更新受影响的 README 查询说明；验证沿用标准库 `unittest`、编译检查和改动文件的 ruff 检查。

## Acceptance Criteria

- [x] **AC1 调用引导**：工具说明明确“中文意图先提炼英文概念词、避免整句、多词可组合、未命中换更短词、命中后细化”；无结果提示与 README 不再暗示模组命令已有中文描述。
- [x] **AC2 多词召回**：以下用例必须调用最终 `search_commands` 输出断言，而不是只检查内部评分；调用时不传 `limit`，使用默认 `limit=8`。固定夹具包含目标根和部分 token 竞争根，逐查询断言预期根及竞争根排除关系，最终文本必须出现指定根和完整目标 syntax，且目标 usage 位于同根前 8 条、排在非匹配 usage 前。

  固定竞争夹具包含 `competitor_quest`/`competitor_editing`、`competitor_waystone`/`competitor_list`、`competitor_channel`/`competitor_mode`、`competitor_radiation`/`competitor_remove`。每个竞争根只提供对应的一个概念 token，不含另一个查询 token；表中预期根必须出现，而只覆盖部分 token 的竞争根不得因根级 AND 误返回。

  | 查询 | 预期根 | 必须出现的完整目标 syntax |
  |---|---|---|
  | `quest editing` | `ftbquests` | `ftbquests editing_mode <enabled> <player>` |
  | `editing quest` | `ftbquests` | `ftbquests editing_mode <enabled> <player>` |
  | `waystone list` | `waystones` | `waystones list <player> all` |
  | `channel mode` | `ae2` | `ae2 channelmode x2` |
  | `radiation removeAll` | `mek` | `mek radiation removeAll` |
  | `remove radiation` | `mek` | `mek radiation removeAll` |

  `mek` 夹具至少包含 10 条普通 usage，必须包含非匹配 usage `mek alpha`；其中至少 9 条在发布校验及 `_group_roots()` 最终排序后均位于 `mek radiation removeAll` 之前，使目标为第 10 条或更后（0 起始索引 `>=9`）。先调用最终 `search_commands("mek", data_dir=...)`（不传 `limit`），按 `mek` 根段解析并断言目标完整 syntax 不在前 8 条展示中，建立基线；再执行 `radiation removeAll` 和 `remove radiation`，断言目标位于该根段前 8 条，并排在固定非匹配 usage `mek alpha` 之前。不能用夹具输入顺序或全文字符串位置替代这些根内排序断言。

  另设独立默认上限夹具：`common`、`common_01` 至 `common_08` 共 9 个根均含共同 token。调用 `search_commands("common", data_dir=...)` 时不传 `limit`，按根段计数必须恰好返回 8 个根，且精确根 `common` 不得被截掉。
- [x] **AC3 匹配边界与回归**：
  - `channel mode`、`channel_mode`、`channel-mode`、`channelmode` 均能召回 `ae2 channelmode x2`；大小写和连续分隔符不改变结果。
  - `botania-skyblock`、`botania_skyblock`、`botania skyblock`、`botaniaskyblock` 均获得同一精确根优先级；`foo`/`foobar`/`afoo` 夹具验证精确根、前缀、包含的排序。
  - `alias target`、`alias -> target` 和单独 `->` 的 redirect 行为符合 R3；redirect target 可参与根级 AND，redirect 不进入普通 usage。
  - 逐项保留并运行既有回归：单 token、原版中文 desc、无匹配、坏快照、两种 producer 提示、按根计数的 `limit`、单根 8 条 usage 上限、纯根、根+子 usage 和 redirect。
  - 新增连续分隔符、大小写和 `->` 结构 token 测试；另加一个边界断言：不同 token 可以分别命中同一根的根名/描述等不同字段而使根级 AND 成立，但不能拼成普通 `matched` usage，只有同一普通 usage 覆盖全部 token 才能进入 `matched`。
  - `clear radiation` 这类需要额外同义词的查询仍允许无结果，不伪造语义。
- [ ] **AC4 真实复验**：使用已归档子任务 1 从下列两个实例分别重新生成并发布的真实快照，不得合并跨实例条目，也不得用临时混合夹具替代。表中路径是重新生成时的原始来源；当前两份文件不存在，不得以历史验收数字代替。实际查询必须使用两个独立 `ASTRBOT_ROOT` 下通过子任务 1 发布流程分别导入的对应副本，不得只把 `/tmp` 隔离目录传给离线函数来替代真实 AstrBot 工具链。每组先确认目标条目已存在，并记录新来源路径、已发布路径、producer、count、SHA-256 和本表逐项目标 syntax；缺文件或缺目标条目时验收阻塞且不得判通过或改用其他快照凑数。

  | 分组 | 逐字用户输入 | 预期根 | 工具原始输出必须出现的完整 syntax |
  |---|---|---|---|
  | Farming | 把酒陈酿到 10 年 | `wine` | `wine age <years>` |
  | Farming | 给 Steve 开启任务编辑模式 | `ftbquests` | `ftbquests editing_mode <enabled> <player>` |
  | Farming | 看看老王激活了哪些传送石碑 | `waystones` | `waystones list <player> all` |
  | CTI | 清掉全服辐射 | `mek` | `mek radiation removeAll` |
  | CTI | 把 AE2 频道模式换一下 | `ae2` | `ae2 channelmode default`、`ae2 channelmode infinite`、`ae2 channelmode x2`、`ae2 channelmode x3`、`ae2 channelmode x4` |

  - Farming 组来源：Minecraft 1.20.1，重新生成 `/home/guigui/mc/Farming/runtime_dump/commands.json`；CTI 组来源：Minecraft 1.19.2，重新生成 `/home/guigui/mc/CTI0.46/runtime_dump/commands.json`。生成后可使用对应隔离副本的等效原始产物，但必须记录真实来源，不得假定旧文件仍在。
  - Farming 与 CTI 各使用一个独立的 `ASTRBOT_ROOT`，已发布路径分别为 `<FARMING_ASTRBOT_ROOT>/data/plugin_data/astrbot_plugin_mc_manager/runtime_dump/commands.json` 和 `<CTI_ASTRBOT_ROOT>/data/plugin_data/astrbot_plugin_mc_manager/runtime_dump/commands.json`。两组使用相同 AstrBot 代码和脱敏配置副本（仅隔离所需的路径等配置可不同）；记录真实 `self.kb.data_dir`、已发布路径和 SHA-256，证明实际工具读取的是对应隔离快照。不新增产品配置项或工具签名。
  - AC1–AC3/AC5 可先完成并保留证据；AC4 的两个新文件/hash、逐项 syntax、工具调用记录和同一模型 5/5 未全部补齐时，任务保持未完成，不能归档。
  - 五条使用同一实际 AstrBot Agent、provider 和 model；验收前记录精确 provider ID、model ID、温度（若可配置，否则记录实际默认值）、Agent/persona 配置版本及脱敏 hash，并禁用 provider/model fallback，中途不得更换。记录会话平台、全新会话创建方式和五个 session ID；每条使用无历史的全新会话，只发送表中的用户输入，不额外提供关键词、根名、目标答案或人工提示。会话内按工具引导换词重试允许，但不得重复新建会话挑选成功结果。
  - 只向模型暴露 `search_mc_commands`：在最终发给 provider 的 `req.func_tool` 断言只有该工具；若当前 AstrBot 不能设置工具白名单，则拦截/mock 所有执行、消息发送和外部写入工具，任何非搜索调用均使该例失败。不得连接 MC 执行命令。记录全部工具调用，确认执行类调用为 0。
  - 保存五次会话的完整记录（含所有同会话重试），以及每次 `search_mc_commands` 的实际 `keyword`、`limit`、完整未截断原始输出和全部工具调用；不得由测试人员额外提示或暗中放大 limit。使用独立临时 AC4 验收 harness 保存原始及已发布快照路径、producer、count、SHA-256 和逐项目标 syntax 预检结果；归档的 `.trellis/tasks/archive/2026-10/10-25-kubejs-command-dump/verify_live.py` 只能参考生成/导入流程，不能作为完整证据采集器，其 `limit=2` 和 `text[:900]` 截断不得用于本验收。**5/5 均须出现表中正确根与全部目标 syntax**；任一失败都不得判定通过，应返回规划分析原因，由用户决定是否评估 rerank 或语义层，实施者不得自行扩大范围。代码修正后必须完整重跑五条，而不是只重跑失败项凑通过。
- [x] **AC5 验证与范围**：相关离线用例、编译及改动文件的 ruff 检查完成；没有自动中文生成、文档抓取、embedding、rerank、新依赖或快照 schema 变更。

### 评审修订后的阶段门禁

- 已获授权的离线 `task.py start` 不因评审修订而阻塞；但 AC2 判定前必须落实 `mek` 基线/根内排序和固定竞争根/默认上限契约（评审 P1-1、P1-2），AC3 判定前必须落实逐项回归映射和新增边界断言（评审 P2-1）。
- AC4 前必须准备独立 `ASTRBOT_ROOT` 接线、固定模型/会话/工具隔离证据和独立未截断 harness（评审 P1-3、P1-4、P2-2）；这些准备不影响离线启动。
- 离线 AC1–AC3/AC5 通过不等于完成或归档；只有 AC4 的两份新真实快照、逐项 syntax、完整工具记录和同一实际模型 5/5 全部满足后，才可申请完成/归档。

## Out of Scope

- 自动生成或人工维护模组中文 `desc`/`aliases`，以及把中文直接搜模组命令作为本期承诺。
- 抓取官方英文文档、文档 RAG、embedding、LLM 候选 rerank、同义词库和模糊拼写搜索。
- 修改 KubeJS/RCON 生产者、命令快照 schema、缓存发布或 RCON 传输。
- 推断 modid、精确权限、命令语义、参数可选性或玩家/RCON 可执行性。
- 取消单根 8 条 usage 上限、无差别返回整棵命令树。
- 为验收实际执行有状态或破坏性 MC 命令。

## 离线实现与验证记录（2026-10-28）

离线 AC1–AC3/AC5 已完成；AC4 未开始，任务保持 `in_progress`。

- **实现**
  - `kb/commands.py`：新增 `_squash()`（小写 + 去空白/下划线/连字符，`->` 整体保留）与 `_split_query()`（按空白/下划线/连字符拆无序 token，连续分隔符不产空 token）；`_score_runtime()` / `_score_vanilla()` 改为 token AND，普通 usage 只有同一条语法覆盖全部 token 才进优先展示；精确/前缀/包含三档仍用整条归一化查询与根名比较。redirect 只参与根级 AND 与提示，显式 `->` 只认 redirect 结构。
  - `main.py`：仅改 `search_mc_commands` docstring（工具描述 + keyword 参数说明），未改逻辑，未整文件 reformat。
  - `README.md`：功能清单与「命令知识库」章节补充英文概念词引导、多词无序 AND、分隔符等价。
  - `tests/test_commands.py`：新增 `IntentSearchTest`（AC2 固定夹具/竞争根/mek 基线/默认上限）与 `IntentBoundaryTest`（AC3 分隔符、精确根优先级、redirect 结构、跨字段 AND 不拼成 matched usage、纯分隔符查询）。
- **验证（/home/guigui/code/AstrBot/.venv/bin/python）**
  - `python -m unittest discover -s tests`：47 tests OK（命令组 36 个，含既有回归）。
  - `python -m compileall -q main.py rcon_client.py runtime_dump.py tools/ kb/ tests/`：通过。
  - `ruff format --check kb/commands.py tests/test_commands.py`：2 files already formatted。`main.py` 不做整文件 reformat（HEAD 本身未格式化，整文件 format 会引入 422 行无关 diff，见 spec/backend/quality-guidelines.md）。
  - `ruff check`：新代码只新增仓库既有 `UP031`/`UP045` 类告警（与周围代码同风格），未新增规则类型。
  - docstring 用 AstrBot 实际解析器 `docstring_parser` 验证：description 515 字含引导，参数仍为 `keyword|string`、`limit|number`。
- **双轴评审与修复（2026-10-28）**
  - Standards 轴：无 P0/P1、硬性违规 0；采纳 P2：抽出共用 `_rank(name, query_norm)` 消除 runtime/vanilla 排名逻辑重复、`_ARROW` 改名 `_ARROW_SENTINEL`；不采纳把 tokens+query_norm 打包成 `_Query`（两个调用点，属过度抽象）。
  - Spec 轴：无 P0/P1；采纳 P2-1 补 `clear radiation` 无结果用例、P2-2 补「运行时根继承中文 desc + usage 跨字段 AND 不拼成 matched usage」用例；P2-4 工具总述措辞不改（次段已澄清，AC1 只点名无结果提示与 README）。
  - Spec P2-3 记录为已知限制不修：多 token 查询的整条归一化串通常不等于/不前缀于根名，因此多词查询落在第 4 档、按根名排序（如 `time set` 会多返回 `/setidletimeout` 且排在 `/time` 前）；忽略分隔符做子串匹配会让短 token（`mc`）跨词边界假命中。这是 R3「用完整查询比较根名」与「子串匹配兼容 quest/ftbquests」的直接代价，真实影响要到 AC4 全量快照才能判断，不在离线阶段扩范围。
- **修复后复验**：49 tests OK（新增 2 个边界用例）；compileall 通过；`ruff format --check kb/commands.py tests/test_commands.py` 已格式化；`kb/commands.py` 仅剩既有 UP031/UP045。
- **Spec 同步**：`.trellis/spec/backend/runtime-dump.md` 新增 3.1.1 查询语义（token AND/分隔符等价/`->` 结构/已知限制）、更新签名表行号（`kb/commands.py:226/386`）、补充 Tests Required 与 Wrong/Correct 两条。
- **未做**：AC4 两份真实快照未生成（`/home/guigui/mc/Farming/runtime_dump/commands.json`、`/home/guigui/mc/CTI0.46/runtime_dump/commands.json` 均不存在，两实例当前未开服）；真实 AstrBot 模型 5/5 未复验。归档前必须补齐。

