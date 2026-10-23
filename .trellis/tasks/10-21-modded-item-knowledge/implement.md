# 执行计划：模组物品认知（修 bug + 物品/翻译知识库）

设计见同目录 design.md。每步完成后勾选。验证命令均从仓库根目录执行。

## 步骤

- [x] 1. **修 4 处硬编码 bug**：新增 tools/id_utils.py 放 `normalize_mc_id()`（`tools/__init__.py` 会先 import 子模块，放这里会循环导入）；替换 game_tools.py:46、game_tools.py:131、world_tools.py:203、world_tools.py:234；同步给这 4 个工具 docstring 补「也可传模组物品完整 ID，如 thermal:tin_ingot」（含 main.py 里 LLM 实际读到的包装器 docstring）。✅ 已完成，验证 ALL PASS。
  - 验证：`python3 -m compileall -q main.py tools/`；临时脚本（stub RCON + set_rcon）调用 give_item("p","thermal:tin_ingot") 与 give_item("p","stone")，确认前者原样、后者补前缀；再确认 clear_inventory("p") 走空分支仍发 `clear p`。
  - 回滚点：此步独立成 commit，与知识库无关。
- [x] 2. **配置项**：_conf_schema.json 加 mc_server_dir / mc_version / mc_client_dir / vanilla_zh_download / cfpa_auto_download；main.py 读取并传给 kb（默认值必须与 schema 一致）。
  - 验证：python3 -m json.tool _conf_schema.json；读一遍 main.py 确认五处默认值相同。
- [x] 3. **kb/store.py**：SQLite schema（items 含 has_item 可为 NULL、meta 含 schema_version）；**每次操作各自 connect/close，不共享连接**；重建走「单事务 DELETE + executemany」保证幂等；LIKE 查询 + 三级排序（完全/前缀/包含）。
  - 验证：临时脚本建库→插 3 条→查询→重复重建两次，确认行数不重复增长、删掉的条目消失。
- [x] 4. **kb/scanner.py**：从 /home/guigui/mc/.research/prototype/scan_items.py 移植裁剪（保留 key→id 规则与三坑处理；has_item 按「item + 带模型 block」判定）。**必须保留 kubejs/assets/*/lang/*.json 资源包层（原型 scan_kubejs 已实现），这是 Farming 中文覆盖的主来源。**
  - 验证：临时脚本扫 /home/guigui/mc/Farming，期望 3.9 万级 id；分层统计应为「仅 jar ≈40.3%、jar+kubejs ≈57.5%」，对照 research/08 §0。
- [x] 5. **kb/vanilla.py（原版，不内置常量表）**：
  - ID + 英文名：按 `libraries/net/minecraft/server/*/server-*-extra.jar` → `-unpacked.jar` → bundler 内嵌 jar 找 `assets/minecraft/lang/en_us.json`；候选取三段键（1,398），与同 jar `data/minecraft/**/*.json` 的 `"minecraft:<id>"` 引用交叉 → 1,369（987 方块 / 382 物品）。
  - 中文（下载为主）：`<数据目录>/vanilla/zh_cn-<mc_version>.json`（缓存/手放）> `<mc_client_dir>/assets`（配了才用）> 官方按版本下载（`vanilla_zh_download`，manifest → 版本 json → assetIndex → resources.download.minecraft.net，sha1 校验、写缓存、BMCLAPI 回退）。**只按 ID 查键，不用 lang 生成 ID。**
  - has_item：有客户端按 `assets/minecraft/models/item/<path>.json` 精确；没有则用服务端 `data/minecraft/loot_tables/blocks/<path>.json` 近似（实测 91.4% 精确 / 98.7% 召回）并标记「推测」；两者都无记 NULL。不下载 client.jar。
  - 验证：临时脚本对 /home/guigui/mc/Farming 跑一遍，期望 1,369 条（987/382）+ 126 实体名，中文命中 100%，耗时 < 1 s；再用不存在的 mc_client_dir 跑一次，确认降级不崩、只警告。
- [x] 6. **kb/cfpa.py**：版本探测（libraries 纯版本目录 > logs/latest.log）、按**离散版本表**选包名、GitHub `/releases/latest`（autobuild）取资产 → BMCLAPI 回退、`<ver>.md5` 校验（内容大写，比较时 lower）、排除 `-Fabric`/`-Namespaced` 变体、zip 解析、缓存与手动放置识别。
  - 验证：临时脚本对 1.20.1 跑一次下载+解析（或直接用 /tmp/cfpa-1-20.zip），统计合法 zh 键数，并确认 `.name` / 含冒号 / 非 item|block|entity|fluid 前缀 / 空值 的键都被剔除（对照 research/08 §1.4 的剔除数）。
- [x] 7. **kb/builder.py**：编排 scan（jar + kubejs）→ vanilla → CFPA 合并（前缀白名单 + 子键过滤，**只对已扫到的 id 生效，不新增 id**）→ zh_cn_extra.json 合并 → 入库 → 统计；zh_source 落 `jar|kubejs|cfpa|extra|vanilla`；统计里把「交叉引用 id」单列；extra 文件 JSON 错误只记日志不中断重建。
  - 验证：临时脚本对 Farming 全量重建，输出与 research/08 §0 对照（Farming 58.8%、zyjd 71.0%）。
- [x] 8. **kubejs dump 合并**：builder 扫 `<mc_server_dir>/runtime_dump/` 与 `<数据目录>/runtime_dump/`，存在则按权威数据合并（同名取 mtime 新）。
- [x] 9. **指令**：main.py 加 mc_kb_rebuild（asyncio.to_thread 异步、权限检查、统计回执 + 原版单行 + 署名）与 mc_kb_status；`terminate()` 里清理知识库持有的资源。
- [x] 10. **LLM 工具**：main.py 加 search_mc_items（docstring 首行带「（无需权限）」），未建库 / 空结果按 design §5.2 的文案返回（区分「库没收录」与「游戏里没有」）；**不注册进 script_executor**。
- [x] 11. **README**：知识库用法、五个配置项说明、zh_cn_extra.json 格式示例、CFPA 署名（CC BY-NC-SA 4.0）、Mojang 资源说明（运行时下载/本机读取，不随插件分发）、不同机限制、原版覆盖率与 33 个无语言键例外。
- [x] 12. **spec 更新（Phase 3.3）**：database-guidelines 补「允许可重建的派生缓存」一段；quality-guidelines §3 免检工具清单 4 → 5（加 search_mc_items）；实际还同步了 error-handling（免检清单 4→5）、directory-structure（新增 kb/ 与 tools/id_utils.py）、quality-guidelines §2（旧的 startswith 前缀示例改为 normalize_mc_id）。

## 总体验证（全部步骤后）

- `python3 -m compileall -q main.py tools/ kb/`
- 用临时脚本对 Farming / zyjd 各跑一遍 rebuild 等价流程，覆盖率须达到 PRD 门槛（Farming ≥55% 全量 / ≥52% give；zyjd ≥67% / ≥68%），并核对与 research/08 的实测值一致。
- search 抽查：中文名 / 英文名 / 完整 ID 三种关键词各查一次模组物品；原版抽查「钻石剑」「石头」「僵尸」应命中 `minecraft:diamond_sword` / `minecraft:stone` / `minecraft:zombie`。
- `grep -rn 'startswith("minecraft:")'` 确认只剩 docstring 示例，没有无条件补前缀的逻辑。
- 真机联调（spec 要求）：装进 AstrBot，`/test_connection`、`/mc_kb_rebuild`、`/mc_kb_status` 各跑一次，让 LLM 实际查一个模组物品并 give。

## 审查门

- 实现完成后按项目流程跑 trellis-check / code-review 再报告完成。

## 风险与回滚

- 步骤 1 独立 commit；知识库（步骤 2-12）为新增文件，可整体 revert，不影响既有工具。
- 步骤 5 依赖服务端 Forge 的 `libraries/`（或客户端/下载兜底）：拿不到时降级为「原版只落英文或只落 ID」，不阻断模组库。

## 实现记录（2026-10-21 本机实测）

- 步骤 1：8 条 stub RCON 断言全过；`compileall` 通过；全仓已无 `startswith("minecraft:")` 逻辑。
- 步骤 4（扫描器）：Farming **39,585** id / `zh_jar=`15,934(40.3%) / `zh_jar+kubejs=`22,769(57.5%) / cross_ref 1,240（80 ns）；zyjd 8,974 / 5,959(66.4%) / 172（22 ns）——与 research/08 逐项一致。
- 步骤 5（原版）：Farming/zyjd 均 1,398 候选 → **1,369**（987 方块 + 382 物品）+ 126 实体名，离线 0.117 s；官方下载 562,116 B（重发布超集）/7.0 s，缓存命中 1,369/1,369=100%；坏 `mc_client_dir` 只告警不崩。
- 步骤 6（CFPA）：解析结果与 `/tmp/zhcov/metrics.py` **完全一致**（映射 4,764 条；过滤计数逐项相同）。线上 autobuild 包的 md5 已变为 `68b16618…`（research/08 时为 `db841d3a…`），所以最终覆盖率略高于当时实测，属预期。
- 步骤 7（整库）：Farming 8.0s / 40,185 条；扫描口径 58.8% / give 56.0%（= research/08）。zyjd 4.5s / 9,380 条；71.0% / 73.1%（= research/08）。整库口径（含原版）Farming 61.2% / give 57.8%，zyjd 83.6% / 83.1%。
- 步骤 8：用 zyjd 运行时 dump 抽样（400 item + 200 block 行）验证合并：新增 448、更新 152、权威 has_item 覆盖 457。
- 步骤 9/10：main.py 接线完成；AstrBot venv 内导入成功，`search_mc_items` 已出现在 func_tool_manager 的 "Added llm tool" 列表；`/mc_kb_rebuild`、`/mc_kb_status` 已注册。
- 真机联调（步骤 9/10 的最后一项）待办：AstrBot 当前进程（PID 102281，10-18 启动）里还是旧代码，需在管理面板重载插件后跑 `/test_connection`、`/mc_kb_rebuild`、`/mc_kb_status` 与一次 LLM 查询。
- 已知偏差（已确认为预期，不修）：实体与物品同 ID（egg/arrow/potion 等 27 个）合并为一行、主类型保留 item/block，便于 give；官方 1.20.1 `zh_cn.json` 是重发布超集，只按 1,369 个 ID 取键，多出的键不进库。

## 审查与修复（code-review 两轴 + 复审）

- 两轴只读审查：标准轴 1 个 P1 + 6 个 P2，规格轴 1 个 P1 + 6 个 P2，两轴都指向同一个 P1：
  **KubeJS runtime dump 链路不闭环**——`assets/runtime_dump.js` 只把 `##RD##` 行写进日志、仓库没有转换器，
  而 README 却承诺「执行 /researchdump 会产出 runtime_dump/*.jsonl」，服主照做永远拿不到 dump。
- 已修 P1：新增 `assets/extract_runtime_dump.py`（日志 `##RD##` → `runtime_dump/*.jsonl`）；
  修正 `assets/runtime_dump.js` 头部说明、删掉一期不消费的 recipe/recipetype 导出；
  README 改为「复制脚本 → /researchdump → 跑转换脚本 → 重建」四步；
  builder 在「检测到 kubejs/ 且没有 dump」时于回执提示这条增强路径（design §3.4 的要求补齐）。
  端到端实测：合成日志 120 条 `##RD##` → extractor 产出 3 个 jsonl → builder 合并 120 条（new=120）。
- 已修 P2（两轴合并去重后）：
  - 文案里 `fill_blocks` 不可达（该函数只是 tools 层函数、未暴露为 LLM 工具）→ 统一改为
    `execute_command` 的 fill；design/prd 同步注明，不新增工具面。
  - `store.search` 补 limit 钳制（1..50）与 LIKE 通配符转义；门面钳制 1..30，main.py 不再写业务逻辑。
  - 扫描器两遍遍历导致 jar 计数翻倍 → 修正常。
  - 回执 kind 统计改用落库 kind（与 SQLite 一致；egg/arrow 这类同 ID 投射物归 item 且可 give）。
  - runtime dump 合并不再覆盖已有主类型；空 jsonl 文件被忽略（不再误判「有 dump」）。
  - 去掉自定义 `BuildError`（改用 ValueError，符合 error-handling「没有自定义异常类」）。
  - CFPA 未使用原因、zh_cn_extra 忽略条数、探测不到 MC 版本的警告都进回执。
  - 清死代码（scanner 空分支、cfpa values/无用 log 参数/重复版本表、builder `_primary_kind`）、
    补 kb 公开函数类型标注、示例换成真实可查的 `create:brass_ingot`、删测试副产物 `data/` 并加 .gitignore。
  - spec `directory-structure` 补 `assets/` 与 `kb/`；.gitignore 增加 `/data/`。
- 复审（新只读子代理，聚焦修复）：**无 P0/P1**，仅 2 个 P2（`_primary_kind` 死代码、空 dump 误判），已一并修完并验证。
- 最终验收：Farming 40,185 条 / 扫描口径 58.8%（≥55 ✓）/ give 56.0%（≥52 ✓）；
  zyjd 9,380 条 / 71.0%（≥67 ✓）/ give 73.1%（≥68 ✓）；原版中文 1,369/1,369；
  compileall、_conf_schema 解析、4 工具 stub 回归、搜索「中文/英文/ID」闭环全部通过。
