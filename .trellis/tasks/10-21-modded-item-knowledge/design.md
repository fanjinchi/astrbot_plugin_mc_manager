# 技术设计：模组物品认知（修 bug + 物品/翻译知识库）

对应 PRD：同目录 prd.md。本文只写技术设计，执行顺序见 implement.md。

## 1. 现状与边界

- 插件是纯 Python AstrBot Star 插件；工具注册 = main.py 里 @filter.llm_tool 装饰器 + docstring Args 段；指令注册 = @filter.command。
- 插件与 MC 服务器只通过 RCON 通信，**现有配置没有任何服务器文件系统路径**。知识库要扫 mods/*.jar，必须新增配置项。
- 数据目录：StarTools.get_data_dir(plugin_name) → AstrBot/data/plugin_data/<plugin>/，SQLite、CFPA zip 缓存、zh_cn_extra.json 都放这里。
- 目标环境以 MC 1.20.1 Forge 为主（两个实测服），一期只保证 1.13+ 的 JSON 语言文件格式；1.12.2 的 .lang 格式不在一期范围内（遇到时明确提示）。

**知识库的定位（与 spec 的关系）**：它是 **mods 目录的派生缓存**——删掉可完整重建、丢了不影响服务器状态、不与 MC 侧或 AstrBot 配置构成双份真相。因此引入 SQLite 不违反 `spec/backend/database-guidelines.md` 现行的"本项目无数据库"约定；但本任务收尾（Phase 3.3）必须把"允许可重建的派生缓存"这条区分补进该 spec，否则后续 agent 会按旧约定把它当违规实现回滚。资源清理：`terminate()` 里关闭任何持有的连接/句柄（按连接即用即关的约定，通常无需额外清理）。

## 2. 硬编码 bug 修复（4 处）

发现 4 处（交接文档记了 3 处，fill_blocks 是第 4 处）：

| 位置 | 现状 |
|---|---|
| tools/game_tools.py:46 give_item | if not item.startswith("minecraft:") → 强制加前缀 |
| tools/game_tools.py:131 clear_inventory | 同上 |
| tools/world_tools.py:203 summon_entity | 同上 |
| tools/world_tools.py:234 fill_blocks | 同上 |

修法：改为「仅当不含命名空间分隔符时补 minecraft:」：

    if ":" not in item:
        item = f"minecraft:{item}"

四处逻辑相同，抽一个公共函数 `normalize_mc_id(raw: str) -> str`，放 **新增的 `tools/id_utils.py`**。

不要放 `tools/__init__.py`：该文件会先 import 四个子模块，子模块再 `from . import _normalize_mc_id` 时包属性尚未初始化，会 ImportError（循环导入）。

- 传 "modid:path" 原样通过；传 "stone" 仍补 minecraft:，行为向后兼容。
- clear_inventory 的 `if item:` 分支保留：item 为空表示"清空整个背包"，归一化函数不能被调用到空值上。
- 同时给这 4 个工具的 docstring 各加一句说明（LLM 靠 docstring 决定传什么）：「也可传模组物品的完整 ID，如 thermal:tin_ingot」。注意真正被 LLM 读到的是 main.py 里 @filter.llm_tool 包装器的 docstring（如 tool_give_item），tools/*.py 里的同名 docstring 只是内部说明，两处都要改。

## 3. 知识库模块结构（新增 kb/ 包）

    kb/
    ├── __init__.py        # 对外导出 KnowledgeBase 门面
    ├── scanner.py         # 离线扫 mods/*.jar：物品/方块 ID + jar 自带语言文件
    ├── cfpa.py            # CFPA 汉化包：版本选择、下载（GitHub→BMCLAPI 回退）、md5 校验、解析
    ├── vanilla.py         # 原版名称：从客户端安装提取 en_us（id 全集）+ assets 里的 zh_cn（名字字典）
    ├── store.py           # SQLite schema + 读写
    ├── builder.py         # 重建编排：scan → 合并 CFPA → 合并 zh_cn_extra → 入库 → 统计
    └── query.py           # 查询接口（供 LLM 工具调用）

scanner.py 由研究原型 /home/guigui/mc/.research/prototype/scan_items.py（716 行纯标准库）移植裁剪，遵循 research/01 的 key→id 规则与三坑（重复注册、环境key、多信源合并）。

### 3.1 数据来源与合并优先级

    zh_cn_extra.json（服主自定义，数据目录内，可选）
        > kubejs/assets/*/lang/zh_cn.json（整合包自带资源包，游戏内最后生效）
            > CFPA 汉化包 zh_cn.json（自动下载或手动放置 zip）
                > 模组 jar 自带 assets/*/lang/zh_cn.json

kubejs 资源包这层不能漏：实测 Farming 有 5 个 zh_cn.json / 23,826 键，单独贡献 10,224 条 id；
不扫它的话 CFPA 相对 jar 只剩 +1.3pp，验收会掉到 48.1%（research/08 §10.1）。

原版（minecraft: 命名空间）单独一条来源：**现场从本机客户端安装提取**，不内置任何常量表（已确认）。

英文名（en_us）来自模组 jar 自带语言文件；CFPA 不提供英文。id → 英文名 的映射是静态扫描的核心产物。

### 3.1.1 原版：服务器安装取英文/ID，中文按优先级取（kb/vanilla.py）

原版名不能来自 mods jar、CFPA 或 slim 服务端 jar（实测：278 个 jar 提供 `assets/minecraft/lang/zh_cn.json` = 0；CFPA 1.20 包内 `assets/minecraft/lang/*` = 0）。但**服务端 Forge 安装里就有官方 en_us**：`libraries/net/minecraft/server/*/server-<ver>-extra.jar`（1.20.1 实测 386,499 B / 6,217 条），`-unpacked.jar` 与 bundler 内嵌 jar 同样有。

- **ID + 英文名（离线、零网络）**：按 `-extra.jar` → `-unpacked.jar` → bundler 内嵌 jar 的顺序找含 `assets/minecraft/lang/en_us.json` 的 jar。候选 = 恰好三段键的 `item.minecraft.*` / `block.minecraft.*`（1,398 个），与同 jar 的 `data/minecraft/**/*.json` 里 `"minecraft:<id>"` 引用交叉，得到 **1,369 个**（987 方块 + 382 物品；对 KubeJS 运行时注册表 1,402 精度 100%、召回 97.6%，耗时 0.11 s）。实现成本高时可退化为候选全集（多约 29 个伪键，如 `minecraft:sign`，不影响常见查询）。
- **中文名（主路径 = 按服务器版本下载，只当字典、不生成 ID）**：按顺序取 `zh_cn.json`——
  1) `<数据目录>/vanilla/zh_cn-<mc_version>.json`（缓存或服主手放）；
  2) `<mc_client_dir>/assets`（配了才用，离线）；
  3) 官方资源运行时下载（`vanilla_zh_download` 默认开：manifest → 版本 json → assetIndex → `resources.download.minecraft.net/<h2>/<hash>`，实测 4 个请求 / 约 1.3 MB / 冷启动 7~8 s，sha1 校验后写入 1) 的缓存；失败回退 BMCLAPI `assets/<h2>/<hash>`）；
  4) 都没有 → 原版只建英文。
  只按已确定的 1,369 个 ID 查键，**绝不用 lang 的键新增 ID**：实测官方 index 现在返回的 1.20.1 zh_cn 是重发布后的超集（8,655 条，含 mace/crafter），真 1.20.1 为 6,215 条。
- **entity 名**：取 `entity.minecraft.*` 三段键（126 条，best-effort，未与注册表交叉验证）。
- **has_item**：item 键 = 1；block 键两档判定（近似结果落 `has_item_guess=1`）：
  有 `mc_client_dir` → 客户端 jar 的 `assets/minecraft/models/item/<path>.json` 精确判定（1/0）；
  没有客户端 → 用服务端 jar 的 `data/minecraft/loot_tables/blocks/<path>.json` 近似（以客户端模型为基准实测：精确率 91.4%、召回率 98.7%；误判是甜菜/瓜藤/蛋糕蜡烛这类「能掉落但没有物品形式」，漏判是基岩/命令方块这类不破坏方块），结果在查询里标注「推测」；
  两者都拿不到 → NULL。
  不下载 client.jar（23 MB）：名字与 ID 不需要它，只为这一个提示位不值得。
- **版本校验**：jar 内 `version.json` 的 id 与 mc_version 比对，不一致只警告不阻断；下载的 zh_cn 命中率 < 95% 时告警并退回英文。
- **实测产出**：1,369 条原版 id（987 方块 + 382 物品）+ 126 条实体名；拿到 zh_cn 时中文 100% 命中；缺的 33 个（17 锻造模板 + 16 墙旗）在 1.20.1 没有语言键，一期接受（KubeJS dump 可补）。
- **许可**：Mojang EULA / Usage Guidelines 禁止再分发游戏资产 → 内置常量表不合规；运行时下载 + 本地缓存风险低；服主自备风险最低。插件不随包分发任何 Minecraft 资产。
- **降级**：拿不到 en_us（服主删了 libraries/、纯 vanilla 也没 bundler）→ 原版不建库；有 en_us 无中文 → 只建英文，查询按 §5.2 的 miss 文案返回。

详细实测见 research/07（服务端 en_us、许可、下载链路）与 research/07a（客户端 assets 路径）。

### 3.2 CFPA 下载（cfpa.py）

规则按 2026-10-21 对线上真实结构的实测校正（见 research/06「实测校正」节）：

- MC 版本确定顺序：配置 mc_version > `<mc_server_dir>/libraries/net/minecraft/server/` 下的纯版本目录（排除带 `-YYYYMMDD` 后缀的那种）> `<mc_server_dir>/logs/latest.log` 里的 `Starting minecraft server version X` > 报错提示服主配置。
  注意：服务器根目录的 `server.jar` 实测不带版本号，不要按 jar 文件名猜；也不必读 jar 内的 version.json。
- 包名是**离散映射表**，不是"主版本取前两位"：

  | MC 版本 | 包名 |
  |---|---|
  | 1.10.2 | Minecraft-Mod-Language-Modpack-1-10-2.zip |
  | 1.12.2 | Minecraft-Mod-Language-Modpack.zip |
  | 1.16 / 1.18 / 1.19 / 1.20 / 1.21 | Minecraft-Mod-Language-Modpack-1-<主>-<次>.zip（如 1.20.1 → `…-1-20.zip`） |
  | 26.1 | Minecraft-Mod-Language-Modpack-26-1.zip |

  1.13 / 1.14 / 1.15 / 1.17 官方没有包：直接提示"该版本暂无 CFPA 包，请手动放置 zip 或关闭 cfpa_auto_download"，不要构造 URL 硬下。
- 资产选择：**必须选不带 `-Fabric` / `-Namespaced` 后缀的正式包**（BMCLAPI 镜像里这些变体同名并存，选错会拿到 Fabric 专用或命名空间变体）。
- 发布源：用 GitHub `/releases/latest`（实测返回 tag `autobuild`，29 个资产、全版本齐全）。**不要**用"时间最新的 Snapshot"——实测 `Snapshot-20261021022338` 只带 1.21 一个版本（2 个资产），1.20.1 会直接找不到包。取不到就按版本表在 `autobuild` 资产里匹配，仍取不到再退 BMCLAPI。
- md5：资产名是 `<版本>.md5`（如 `1.20.md5`），**不是** zip 同名；内容是**大写** 32 位 hex，比较时必须 lower()。
- 下载顺序：GitHub `autobuild` 资产的 `browser_download_url` → 失败回退 BMCLAPI 镜像根目录（HTML 目录列表，正则取 `Minecraft-Mod-Language-Modpack-*.zip` 与 `.md5`）。下载后必须校验 md5。
- 缓存：zip 存数据目录 cfpa/ 下，文件名用标准包名；重建时若已有同 md5 的缓存可复用。
- 手动兜底：服主把 zip 放到数据目录 cfpa/ 下即被识别（断网/无包版本）；识别规则 = cfpa/ 下所有 *.zip，优先标准包名，否则取 mtime 最新者。
- 全程标准库：urllib.request + zipfile + hashlib + json。

### 3.3 SQLite schema（store.py）

    CREATE TABLE items (
      item_id TEXT PRIMARY KEY,   -- 完整 ID，如 thermal:tin_ingot
      namespace TEXT NOT NULL,    -- modid
      path TEXT NOT NULL,         -- 注册名路径段
      kind TEXT NOT NULL,         -- item | block | fluid | entity
      has_item INTEGER,         -- 1=有物品形式(可 give)、0=无(只能 fill)、NULL=未知
      has_item_guess INTEGER NOT NULL DEFAULT 0,  -- 1=has_item 来自 loot 表近似（未配客户端），查询里标注「推测」
      name_en TEXT,               -- jar en_us 键名翻译
      name_zh TEXT,               -- 合并后的中文名
      zh_source TEXT,             -- extra | kubejs | cfpa | jar | vanilla
      mod_name TEXT               -- 模组显示名（来自 mods.toml/fabric.mod.json）
    );
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);  -- schema_version / 构建时间 / MC版本 / 统计 / CFPA快照tag

- `has_item` 的理由：research/05 实测 give 可用 = item + 带模型 block（Farming 32,152 / 39,585），纯技术方块只能用于 fill。查询结果把这条带给模型，避免它对技术方块调 give_item。原版方块在没配客户端时无法判定，记 NULL 并在文案里说明「可尝试 give」。
- 模糊查询用 LIKE %kw%（同时匹配 item_id/name_en/name_zh）：Farming 实测全量约 3.96 万行，全表 LIKE 仍在毫秒级，不引入 FTS5（中文分词与 trigram 可用性都不稳）。
- 排序：完全匹配 > 前缀匹配 > 包含匹配，同分按 namespace 字母序，保证结果稳定可复现。
- **连接策略（必须照做，否则线程报错）**：sqlite3 默认 `check_same_thread=True`，而 builder 在 `asyncio.to_thread` 线程里写、查询工具在事件循环线程里读。约定每次操作各自 `sqlite3.connect(db_path)`（配 contextmanager 关闭），**不共享模块级连接**，也不用 `check_same_thread=False`。
- **重建幂等**：单事务内 `DELETE FROM items` + `executemany` 全量写入，再更新 meta；不做增量 upsert（否则删掉的 mod 会留僵尸行）。

### 3.4 KubeJS 运行时 dump 增强（可选路径）

- 检测到 <mc_server_dir>/kubejs/ 存在时，重建指令提示可选增强：脚本已入库 `assets/runtime_dump.js`（只导出 item/block/entity/fluid），配套 `assets/extract_runtime_dump.py` 把日志里的 `##RD##` 行转成 `runtime_dump/*.jsonl`（脚本本身只写日志、不落盘，必须走这一步）；
- builder 同时扫两处 `runtime_dump/*.jsonl`：`<mc_server_dir>/runtime_dump/`（dump 脚本直接落盘）与 `<数据目录>/runtime_dump/`（AstrBot 与 MC 不同机时人工拷贝）；两处都有同名文件时按 mtime 取新。存在即合并为权威数据（覆盖同 ID 的静态扫描结果）。
- 一期只做到「有 dump 文件就合并」，不做任何自动下发/自动执行。

## 4. 配置项新增（_conf_schema.json）

| key | 类型 | 默认 | 说明 |
|---|---|---|---|
| mc_server_dir | string | "" | MC 服务器根目录（含 mods/ 的路径），空 = 知识库功能不可用并提示 |
| mc_version | string | "" | MC 版本（如 1.20.1），空 = 自动探测（libraries 纯版本目录 > logs/latest.log），探测失败报错提示配置 |
| mc_client_dir | string | "" | 客户端 .minecraft 目录（可选，离线增强）。用于离线取原版中文名与精确 has_item；空 = 中文走官方下载/手放，has_item 走 loot 近似 |
| vanilla_zh_download | bool | true | 重建时是否自动下载官方原版 zh_cn.json（按 MC 版本，sha1 校验、缓存、BMCLAPI 回退） |
| cfpa_auto_download | bool | true | 重建时是否自动下载 CFPA 汉化包 |

zh_cn_extra.json 格式（服主手写，放数据目录，可选）：顶层 JSON 对象，key 为完整 ID（`thermal:tin_ingot`），也接受 lang key 形态（`item.thermal.tin_ingot`）；value 为中文名字符串。示例：

    {"create:brass_ingot": "黄铜锭", "item.create.cogwheel": "齿轮"}

解析失败时记日志并跳过该文件，不中断重建（服主手写文件最容易出 JSON 语法错）。

限制声明：AstrBot 与 MC 服务器不同机时无法离线扫 jar（RCON 不给文件访问），README 注明此限制与手动放置 CFPA zip 的替代路径。

## 5. 指令与 LLM 工具

### 5.1 指令（@filter.command，走现有 _check_permission）

- mc_kb_rebuild：重建知识库。完成后回执统计：物品/方块/流体/实体条数、中文覆盖率（kubejs / CFPA / jar / extra 各贡献多少）、CFPA 快照版本、耗时；原版单列一行（如「原版：1,369（方块 987 / 物品 382），中文 1,369（官方 zh_cn）」）。输出末尾附来源署名（CC BY-NC-SA 4.0 与 Mojang 资源说明）。
- 回执里把「交叉引用 id」（引用了未安装 mod 的 id）单列，避免服主误以为游戏里真多了几百个物品（research/08 §10.3）。
- mc_kb_status：显示当前知识库统计与构建信息（只读，轻量）。

### 5.2 LLM 工具（@filter.llm_tool，免权限、只读）

- search_mc_items(keyword, limit=10)：中文名/英文名/物品 ID 模糊搜索，返回 `modid:path`、中文名、英文名、所属模组、类型，以及「无物品形式（仅可用于 fill）」提示（has_item=0 时；has_item_guess=1 时为「推测可 give」；NULL 时提示「可尝试 give，失败则只能 fill」）。知识库未构建时返回「请先让管理员运行 mc_kb_rebuild」。
- **命中为空时**返回（已与用户确认，按实际可用工具校正）：`知识库未收录「<kw>」。若这是原版物品（如 diamond_sword），可直接用原版 ID 调用 give_item，或用 execute_command 执行 fill 命令。` —— 避免模型把"库里没有"误报成"不存在"。
- 免权限的写法照现有约定：docstring 首行带「（无需权限）」（现有 4 个：list_players / whitelist_list / banlist / list_script_tools），并在 spec/backend/quality-guidelines.md §3 的清单里登记第 5 个。
- **不注册进 script_executor**：它是查询而不是命令类工具，execute_script 场景用不到；list_script_tools 的 categories 也不动。若后续有脚本需求再加。

只加一个查询工具：返回的完整 ID 可直接用于 give_item / summon_entity；填方块走已有的 execute_command（fill），形成「查→用」闭环，不拆 exact-match 工具。
注：`fill_blocks` 目前只是 tools 层函数（未暴露为 LLM 工具），本次只修它的 ID 归一化 bug，不新增工具面。

## 6. 兼容与风险

- 回归面：4 处 ID 规范化是纯前缀逻辑收窄（原来是超集行为），原版短名路径不变；现有 30 个工具不动。
- 风险与实测校正：不要解析 Releases 的 HTML，也不要"取最新 Snapshot"（实测最新 Snapshot 只带单个版本）。一次 `GET /releases/latest` 就能拿到 `autobuild` 的全版本资产列表；API 无 token 时限流 60 次/小时，够用，403 时退 BMCLAPI 的 HTML 目录列表（正则取 zip 与 md5）。
- 风险：Mojang 资产链可能返回与版本不符的 lang（实测官方 index 的 1.20.1 zh_cn 含 1.21 内容，8,655 条）→ 只按已确定的 ID 查键、不生成 ID；下载后校验命中率，< 95% 告警并退回英文。
- 风险：CFPA 包内 key 有大量噪声（1.20 包实测 126,813 个 key：block.* 60,565、item.* 20,862、entity.* 2,218，另有 535 个 `.name` 后缀键、1,377 个含冒号的键如 `hexcasting.action.appendhextome:read`）。合并时必须白名单前缀（item./block./entity.）+ 丢弃 `.name` 后缀 + 丢弃含冒号 key + 按 research/01 的子键规则丢弃四段以上子键，否则会造出假 item。
- 风险：扫描耗时长（Farming 6.9s/171MB）→ 重建指令异步执行并回报进度，不阻塞事件循环（asyncio.to_thread）。
- 合规：CFPA zip 不进 git；README 与重建回执都带署名。

## 7. 回滚

- 知识库功能全部为新增文件 + 新配置项（有默认值），回滚 = revert；bug 修复为独立小 commit，可单独 revert。
