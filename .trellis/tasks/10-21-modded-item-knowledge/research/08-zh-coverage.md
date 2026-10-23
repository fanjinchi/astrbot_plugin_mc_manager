# 08 — 两台真实服务器中文覆盖率实测（验收门槛定数）

> 实测时间：2026-10-21（本机）｜数据：/home/guigui/mc/Farming（1.20.1 Forge，278 jar / 310 mod）、/home/guigui/mc/zyjd（1.20.1 Forge，228 jar / 243 mod）、CFPA 1.20 包 `/tmp/cfpa-1-20.zip`（md5 `db841d3af759ace3037c96248414cedb`）
> 目的：把 prd.md 里"接入 CFPA 后中文覆盖率有可量化提升"这条模糊验收标准，换成用实测数字支撑的硬门槛。
> 原始目录全程只读；原型 `/home/guigui/mc/.research/prototype/scan_items.py` 未修改，本轮脚本全部在 `/tmp/zhcov/`。

---

## 0. 结论速览

| 口径（分母 = 还原出的全部 id） | Farming | zyjd |
|---|---|---|
| id 总数 | 39,585 | 8,974 |
| **仅 jar 自带 zh_cn** | **15,934（40.3%）** | **5,959（66.4%）** |
| jar + CFPA | 19,056（48.1%） | 6,376（71.0%） |
| jar + 整合包 kubejs 资源包 | 22,769（57.5%） | 5,959（66.4%） |
| **jar + kubejs + CFPA（最终库）** | **23,286（58.8%）** | **6,376（71.0%）** |
| 同上，give 可用子集 | 17,996 / 32,152（**56.0%**） | 5,275 / 7,213（**73.1%**） |

三个必须说清楚的事实：

1. **research/05 的四个核心数字全部精确复现**：Farming 39,585 / 22,769 / 32,152 / 17,517，zyjd 8,974 / 5,959 / 7,213 / 4,984。差异只在解释和口径细化（见第 9 节）。
2. **CFPA 的边际增益取决于基线**：相对"仅 jar 自带"是 +7.8pp（Farming）/ +4.6pp（zyjd）；相对"jar + 整合包 kubejs 资源包"（= 玩家现在游戏里实际看到的状态）只剩 **+1.3pp / +4.6pp**。Farming 的中文主要来自整合包作者自己写的 kubejs 资源包（10,224 条 id），不是 CFPA。
3. **CFPA 完全解决不了原版**：CFPA 里 3,270 条 `item.minecraft.*` / `block.minecraft.*` 键全是药水变体和模组方块，**没有一条** `item.minecraft.diamond_sword` 这类原版物品名，且一条都对不上已扫 id。原版不能靠内置常量表（EULA 禁止再分发）；改用服务端 en_us + 外部 zh_cn（research/07 定案）。

---

## 1. 指标口径（复现前必读）

### 1.1 id 全集从哪来

沿用原型 `scan_items.py` 的产物，**不新增任何规则**：pass1 收集 data/资源里的"硬 id"（tag / recipe / loot / model / blockstate），pass2 用硬 id 解析 lang key（`kind.namespace.path` → `namespace:path`，整串 id 优先 > 首段 > 去末段），再合并 kubejs（assets 语言文件 + data + 脚本字面量 + `StartupEvents.registry`）。子 key（`.desc` / `.tooltip` / 药水变体等 4 段以上）丢弃，不覆盖父 id 的名字。

- 本轮只给原型加了一层"记录名字来源"（`/tmp/zhcov/layers.py`，import 原型的 `Collector` 后重写 `set_name`），其余逻辑 100% 复用，产物与原型逐条一致（39,585 / 22,769 / 26,776 与原型输出完全相同）。
- **id 全集包含两类"水分"**，都在分母里，必须知道：① 命名空间没有任何 jar 提供 assets 的交叉引用 id：Farming 1,240 条（3.1%，80 个 ns）、zyjd 172 条（1.9%）——它们来自别的 mod 的 tag/recipe 里引用了未安装 mod 的 id；② 只有 `models/item/*.json`、任何语言层都没名字的 id：Farming 1,159 条、zyjd 875 条（抽样多为 `slingshot_pulling_1`、`abacus_26`、`*_copper_trim` 这类状态变体模型）。

### 1.2 什么算"有中文"

**主口径**：该 id 在某一中文层解析出了**非空**译名（游戏内会以该名字显示）。

- `jar` 层 = `mods/*.jar`（含 jar-in-jar 递归）里 `assets/*/lang/zh_cn.json` 的 `item.` / `block.` / `entity.` / `fluid.` 键，且不是子 key；
- `kubejs` 层 = 整合包 `kubejs/assets/*/lang/zh_cn.json`（资源包层，游戏里最后生效）。注意 lang 文件是**全局合并**的，键的第二段才是命名空间；
- `cfpa` 层 = CFPA 1.20 包的 596 个 `assets/*/lang/zh_cn.json`，映射规则见 1.4，且**只对已扫描到的 id 生效**（不新增 id，否则会把没装的 mod 算进来）。

**质量校验（不参与主口径，仅证明分母没被灌水）**：最终中文值里真正包含 CJK 字符的比例 —— Farming 23,211/23,286（99.7%，整表 58.6%）、zyjd 6,302/6,376（98.8%，整表 70.2%）；中文值恰好等于英文名的只有 72 / 73 条。即"有中文"没有被空串或英文占位符撑起来。

### 1.3 give 可用（与 05 完全一致，可精确复现）

`kind(互斥) == "item"` **或**（`kinds` 含 block 且 sources 含 model，即方块有 item 模型 → 有 BlockItem）；并且 `kinds` **不含** entity/fluid。

这个"不含 entity/fluid"的条件是复现 05 数字的关键：去掉它 Farming 会多出 5 条（32,157）、zyjd 多出 13 条（7,226），覆盖率也会跟着偏移。本文全程用 32,152 / 7,213 这一口径，因此与 05 逐位对齐。

敏感性（门槛论证用）：换成"kinds 含 item 即算"的宽松口径，Farming 32,152→34,143 条、覆盖率 56.0%→57.3%；zyjd 7,213→7,551、73.1%→71.2%。换口径带来的波动 ≤2pp。

### 1.4 CFPA 合并规则与非法 key 过滤

包内实测：**596 个 `assets/*/lang/zh_cn.json`，合计 126,669 个 key**（另有 6 个 `.flatten.json5` 和 2 个 1.12.2 的 `zh_cn.lang`，共 916 个 key，实现应直接跳过 —— 这也解释了任务书里的 597 / 126,813 是"`zh_cn.*` 全匹配 + 含 json5/lang"的数）。

过滤与映射（顺序不能反，先过滤再映射）：

| 步骤 | 规则 | 实测剔除数 |
|---|---|---|
| 1 | value 为空/纯空白 → 丢 | 919 |
| 2 | key 以 `.name` 结尾（1.12.2 遗留）→ 丢 | 534 |
| 3 | key 含 `:` → 丢 | 1,372 |
| 4 | 前缀不是 item/block/entity/fluid（`gui.` `tooltip.` `advancements.` `text.` `subtitles.` …）→ 丢 | 40,456 |
| 5 | 映射：整串 `seg[1]:rest.join(".")` 命中已扫 id → 用整串；`seg[1]:rest[0]` 命中 → 用首段，且 `len(rest)>1` 判为子 key 丢弃；`seg[1]:rest[:-1]` 命中 → 子 key 丢弃；都不中 → 未匹配 | 子 key 4,029 / 未匹配 74,559 |
| 6 | 只留已扫 id（未匹配的 74,559 里 477/536 个命名空间本服根本没装） | 命中 4,764 条 id，36 条同名冲突 |

> 任务书给的是"535 个 .name、1,377 个含冒号"，本次按顺序过滤后是 534 / 1,372 —— 差值 1/5 来自 6 个 key 同时满足两个条件（`block.minecraft.banner.supplementaries.dragon.black` 这种既带冒号又带 .name 的极端键），属于统计顺序差异，不是包变了。

### 1.5 分母

两个分母都报：**全部 id**（39,585 / 8,974，即知识库 items 表的行数，也是 `mc_kb_rebuild` 回执会报的数）和 **give 可用 id**（32,152 / 7,213）。中文覆盖率 = 有中文的 id 数 ÷ 分母。

---

## 2. 复现

### 2.1 脚本（全部在 /tmp/zhcov，纯标准库）

| 脚本 | 作用 |
|---|---|
| `/tmp/zhcov/layers.py` | 复用原型扫描，额外记录每个 id 的中文/英文来自哪一层，产出 `.layers.tsv`（id,kinds,sources,zh层,en层）+ `.names.tsv` |
| `/tmp/zhcov/metrics.py` | 分层覆盖率、CFPA 合并、kind/give 统计、命名空间缺口、CFPA 过滤统计（导出 JSON） |
| `/tmp/zhcov/inventory.py` | 命名空间清单：哪个 jar 提供 `assets/<ns>`，en_us/zh_cn 文件数与该 ns 的 key 数（区分"模组没带中文"和"我们没解析出来"） |
| `/tmp/zhcov/gaps.py` | 缺口 TopN 归因 + 对每个有 zh_cn 的 ns 做 key 级映射率 |
| `/tmp/zhcov/query.py` | 查询可用性实测（抽样 + 三种查询方式） |
| `/tmp/zhcov/summary.py`、`probe*.py` | 口径敏感性与边角核实 |

### 2.2 命令与耗时（实测，单线程）

```bash
# 0) 原型基线（复核 05 用）
/usr/bin/time -v python3 /home/guigui/mc/.research/prototype/scan_items.py /home/guigui/mc/Farming --out /tmp/zhcov/out/farming
#   -> 最终 id 39585 / 有中文 22769 / 有英文 26776；7.12 s，峰值 167 MB
/usr/bin/time -v python3 /home/guigui/mc/.research/prototype/scan_items.py /home/guigui/mc/zyjd --out /tmp/zhcov/out/zyjd
#   -> 8974 / 5959 / 6590；2.46 s，峰值 297 MB

# 1) 分层扫描（约等于原型一次完整扫描）
python3 /tmp/zhcov/layers.py /home/guigui/mc/Farming /tmp/zhcov/out/farming   # 6.59 s / 157 MB
python3 /tmp/zhcov/layers.py /home/guigui/mc/zyjd    /tmp/zhcov/out/zyjd      # 2.38 s / 295 MB

# 2) 合并 CFPA + 出全部指标
python3 /tmp/zhcov/metrics.py /tmp/zhcov/out/farming /tmp/cfpa-1-20.zip /tmp/zhcov/out/farming.metrics.json  # 0.51 s / 100 MB
python3 /tmp/zhcov/metrics.py /tmp/zhcov/out/zyjd    /tmp/cfpa-1-20.zip /tmp/zhcov/out/zyjd.metrics.json     # 0.24 s / 35 MB

# 3) 命名空间清单 / 缺口归因 / 查询实测
python3 /tmp/zhcov/inventory.py /home/guigui/mc/Farming /tmp/zhcov/out/farming.inv.json   # 1.35 s
python3 /tmp/zhcov/gaps.py      /tmp/zhcov/out/farming /tmp/cfpa-1-20.zip /tmp/zhcov/out/farming.inv.json
python3 /tmp/zhcov/query.py     /tmp/zhcov/out/farming /tmp/cfpa-1-20.zip 20261021
```

全流程（扫描 + CFPA 合并 + 全部指标）**单服 < 10 秒、峰值 < 300 MB**；查询侧不需要把 39,585 行全留在内存里，设计里的"每次操作各自 connect"完全够用。

### 2.3 产物（可作为证据复核）

`/tmp/zhcov/out/{farming,zyjd}.metrics.json`（全量指标）、`*.layers.tsv` / `*.names.tsv`（逐 id 分层）、`*.inv.json`（命名空间清单）、`*.query.txt`（抽样明细）、`*.log`（原型统计）。

---

## 3. 指标 1：id 与类型

| | Farming | zyjd |
|---|---|---|
| 还原出的 id 总数 | **39,585** | **8,974** |
| 互斥 kind：item / block / fluid / entity | 11,048 / 27,552 / 289 / 696 | 4,351 / 3,817 / 21 / 785 |
| kinds 含：item / block / entity / fluid | 34,143 / 27,598 / 696 / 289 | 7,551 / 3,836 / 785 / 21 |
| **give 可用**（1.3 口径） | **32,152** | **7,213** |
| └ 其中"有 item 模型的方块" | 21,104 | 2,862 |
| 方块总数（含只能 fill 的技术方块） | 27,598 | 3,836 |
| 无 item 模型的方块（不可 give） | 6,489 | 961 |

说明：item 与 block 大面积重叠（BlockItem），所以"互斥 kind"加起来是 39,585，而"kinds 含 item"是 34,143 —— 两个数都对，别混用。give 可用 = 互斥 item（11,048）+ 有模型方块（21,104）。

---

## 4. 指标 2：仅用 jar 自带翻译

| | Farming | zyjd |
|---|---|---|
| 有 en_us 的 id（jar 层） | 22,481（56.8%） | 6,590（73.4%） |
| 有 zh_cn 的 id（jar 层） | **15,934（40.3%）** | **5,959（66.4%）** |
| 分母 = 全部 id | 15,934 / 39,585 = **40.3%** | 5,959 / 8,974 = **66.4%** |
| 分母 = give 可用 id | 14,359 / 32,152 = **44.7%** | 4,984 / 7,213 = **69.1%** |
| 无任何名字的 id（不含 CFPA） | 12,809 | 2,316 |

补充：`kubejs/config/english_translation.json` 是**英文别名表**（13,698 键，覆盖 10,633 条 id），本文不把它算作"英文层"；05 报的"有英文 26,776" = 22,481 + 这块多出来的 4,295。

---

## 5. 指标 3：合并 CFPA 后

### 5.1 四层组合（同一分母，便于对照）

| 组合 | Farming 全量 | Farming give | zyjd 全量 | zyjd give |
|---|---|---|---|---|
| A 仅 jar | 15,934（40.3%） | 14,359（44.7%） | 5,959（66.4%） | 4,984（69.1%） |
| B jar + CFPA | 19,056（48.1%） | 15,410（47.9%） | 6,376（71.0%） | 5,275（73.1%） |
| C jar + kubejs | 22,769（57.5%） | 17,517（54.5%） | 5,959（66.4%） | 4,984（69.1%） |
| **D jar + kubejs + CFPA** | **23,286（58.8%）** | **17,996（56.0%）** | **6,376（71.0%）** | **5,275（73.1%）** |

提升的绝对条数/百分点：

| 对比 | Farming 全量 | Farming give | zyjd 全量 | zyjd give |
|---|---|---|---|---|
| A → B（CFPA 单独） | +3,122 / **+7.8pp** | +1,051 / +3.2pp | +417 / **+4.6pp** | +291 / +4.0pp |
| A → D（实现最终态） | +7,352 / **+18.5pp** | +3,637 / **+11.3pp** | +417 / **+4.6pp** | +291 / +4.0pp |
| C → D（CFPA 边际） | +517 / +1.3pp | +479 / +1.5pp | +417 / +4.6pp | +291 / +4.0pp |

- Farming 的 +6,835 条（C 相对 A）来自整合包自带的 kubejs 资源包（`kubejs/assets/minecraft/lang/zh_cn.json` 15,910 键 + `farmingtales_english` 4,992 键等 8 个文件）。**不扫这一层，Farming 只能到 48.1%。**
- kubejs 层覆盖 10,224 条 id，其中 3,389 条 jar 里也有（重叠），6,835 条是它独有的。

### 5.2 CFPA 到底补到了谁

Farming：CFPA 命中 4,764 条 id，其中 4,247 条原本就有中文，**净新增 517 条**。净新增的命名空间分布：

| ns | 新增 | ns | 新增 |
|---|---|---|---|
| biomeswevegone | 63 | spawn | 48 |
| naturalist | 62 | biomesoplenty | 42 |
| regions_unexplored | 60 | atmospheric | 41 |
| immersiveengineering | 40 | sob | 33 |
| farmersrespite | 28 | environmental | 19 |

**但前几名全是本服没装的 mod**（biomeswevegone / regions_unexplored / biomesoplenty / atmospheric / immersiveengineering / environmental），它们只是被别的 mod 的 tag/recipe 引用而在 id 全集里留了名。517 条净新增里 **269 条落在这类"交叉引用 id"上**，游戏里根本不存在这些物品；真正能显示的中文是 **248 条**。

zyjd：CFPA 净新增 417 条（neapolitan 116、naturalist 71、environmental 54、oceanic_delight 47、realmrpg_skeletons 29、upgrade_aquatic 26…），其中 129 条是交叉引用 id，真实 288 条。

### 5.3 为什么 CFPA 的边际增益这么小

CFPA 1.20 包的 536 个命名空间里，本服真的有 jar 资源的：Farming **39 个**、zyjd 更少；其余 477 个装了也白装。已装命名空间里 12,433 个可映射 key 只对上 3,178 条（25.6%），落空的三大来源：

| 来源 | 例子 | 说明 |
|---|---|---|
| 原版 key | `item.minecraft.splash_potion.effect.health_boost` | 3,265 条 `minecraft.*` 键里只有 2 条对上；CFPA 没有原版物品名 |
| 动态生成 / 未安装 | `everycomp` 3,141 条、`chipped` 7,086 条 | EveryCompat 的方块运行时才生成，静态没有 model/blockstate 可扫；chipped 本服没装 |
| 模组本身没中文 | bf_blockpack / cluttered / paintable / yuushya | 这几家合计 9,313 条 id，jar 和 CFPA 都没有中文 |

反过来说：CFPA 对"模组自己带了 zh_cn 但只有一部分"的情况是真的有用（realmrpg_skeletons 从 0 到 29、spawn 从 2 到 61、supplementaries +2），只是这些模组在两服里体量都不大。

---

## 6. 指标 4：原版（minecraft: 命名空间）

| | Farming | zyjd |
|---|---|---|
| minecraft: id 条数 | **1,460** | **1,090** |
| 有中文 | **164（11.2%）** | **3（0.3%）** |
| 有英文 | **2** | **2** |
| 中文来源 | kubejs 资源包 160 条 + jar 2 条 + CFPA 2 条 | jar 2 条 + CFPA 1 条 |

- 原因不是解析不到，是**服务端安装里没有原版语言文件**：278 个 jar 里提供 `assets/minecraft/lang/zh_cn.json` 的是 0 个（`en_us.json` 同样 0 个），服务端也不含客户端 assets。
- **CFPA 不是解药**：CFPA 里 3,270 条 `minecraft.*` 键（block 2,561 / item 672 / entity 37）全部是模组内容借用 minecraft 命名空间（`runelic` 816 条、`archaeologybanners` 768 条）或药水变体，对 `minecraft:diamond_sword` 这类 id **一条都没有**。实测这 3,270 条里对上已扫 id 的是 **0 条**。
- 这个数字和 05 的"约 199 个有中文"不一致，见 9.3 下方表格里的"原版有中文"行。

---

## 7. 指标 5：查询可用性（随机 20 个，中文名/英文名/完整 id）

查询实现按 design.md 3.3 的真实规划：`LIKE %kw%` 同时匹配 `item_id / name_zh / name_en`，排序 = 完全匹配 > 前缀 > 包含，同分按 namespace 字母序，**limit=10**。命中 = 目标 id 出现在前 10 条（括号里是名次）。脚本：`query.py`，seed=20261021。

### 7.1 Farming（物品 10 + 带模型方块 10，从全量 id 随机抽）

| kind | id | 中文名 | 英文名 | 中文查询 | 英文查询 | id 查询 |
|---|---|---|---|---|---|---|
| item | supplementaries:slingshot_pulling_1 | - | - | 无名字 | 无名字 | #1 |
| item | ordertocook_chair_compat:redeco/light_gray_sofa | - | - | 无名字 | 无名字 | #1 |
| item | wallpapers:cerulean_wallpaper_roll_dma | - | Cerulean Wallpaper Roll | 无名字 | #1 | #1 |
| item | armamentarium:thunder_whetstone | 雷霆充能砥石 | Thunder-Charged Whetstone | #1 | #1 | #1 |
| item | ordertocook_chair_compat:quark/black_stool | - | - | 无名字 | 无名字 | #1 |
| item | quark:abacus_26 | - | - | 无名字 | 无名字 | #1 |
| item | laowu:super_health_cat_can | 超级猫罐头-生命 | Super Cat Can - Health | #1 | #1 | #1 |
| item | farmingtales:pink_swamp_oak_door | - | - | 无名字 | 无名字 | #1 |
| item | selfexpression:lawer_chestplate | 律师外套 | Lawer's jacket | #1 | #1 | #1 |
| item | papercraft_magic_decoration:raw_manga_meat | 生的漫画肉 | Raw Manga Meat | #1 | #1 | #1 |
| block | railways:track_natures_spirit_olive_narrow | 橄榄木列车窄轨 | Narrow Olive Train Track | #1 | #1 | #1 |
| block | another_furniture:acacia_flower_box | 金合欢木花箱 | Acacia Flower Box | #1 | #1 | #1 |
| block | kaleidoscope_cookery:cold_roasted_meat | 冷肉炙 | Cold Roasted Meat | #1 | #1 | #1 |
| block | bf_blockpack:bushy_yellow_leaves | - | Bushy Yellow Leaves | 无名字 | #1 | #1 |
| block | bloomingnature:foxglove_white | 白色毛地黄 | Foxglove White | #1 | #1 | #1 |
| block | yuushya:stairs_white_wool | - | - | 无名字 | 无名字 | #1 |
| block | yuushya:post_pink_wool | - | - | 无名字 | 无名字 | #1 |
| block | yuushya:stick_stripped_warped_stem | - | - | 无名字 | 无名字 | #1 |
| block | bountifulfares:hoary_log | 朽老木原木 | Hoary Log | #1 | #1 | #1 |
| block | create:cut_veridium_brick_slab | 切制辉绿岩砖块台阶 | Cut Veridium Brick Slab | #1 | #1 | #1 |

**命中率：中文 10/20（50%）｜英文 12/20（60%）｜完整 id 20/20（100%）。**
但分母要看清：10 条**库里没有中文名**（yuushya 3 条、bf_blockpack 1 条、状态变体/联动家具 6 条），中文查询根本无从发起；**有中文名的 10 条，10/10 命中且 10/10 在首位**。英文同理 12/12、全部首位。

### 7.2 zyjd（同样 10+10）

| kind | id | 中文名 | 英文名 | 中文查询 | 英文查询 | id 查询 |
|---|---|---|---|---|---|---|
| item | epicfightx:great_tachi_parent | - | - | 无名字 | 无名字 | #1 |
| item | delightful:honey_glazed_walnut | 琥珀核桃 | Honey Glazed Walnut | #1 | #1 | #1 |
| item | farmersdelight:diamond_knife | 钻石刀 | Diamond Knife | #1 | #1 | #1 |
| item | saintsdragons:nulljaw_spawn_egg | 虚颚龙刷怪蛋 | Nulljaw Spawn Egg | #1 | #1 | #1 |
| item | aether:blue_moa_egg | 蓝色恐鸟蛋 | Blue Moa Egg | #1 | #1 | #1 |
| item | delightful:experience_knife | 经验刀 | Experience Knife | #1 | #1 | #1 |
| item | duel_dimension:abyss_watcher_spawn_egg | 凝渊人刷怪蛋 | Abyss Watcher Spawn Egg | #1 | #1 | #1 |
| item | bygonenether:gilded_netherite_helmet | 镶金下界合金头盔 | Gilded Netherite Helmet | #1 | #1 | #1 |
| item | irons_spellbooks:fire_cloth | - | - | 无名字 | 无名字 | #1 |
| item | irons_spellbooks:greater_invisibility_elixir | 强效隐身药剂 | Greater Invisibility Elixir | #1 | #1 | #1 |
| block | biomesoplenty:willow_fence | 柳木栅栏 | Willow Fence | #1 | #1 | #1 |
| block | quark:chiseled_myalite_bricks | 雕纹幻境石砖 | Chiseled Myalite Bricks | #1 | #1 | #1 |
| block | irons_spellbooks:wisewood_chiseled_bookshelf | 智慧木雕纹书架 | Wisewood Chiseled Bookshelf | #1 | #1 | #1 |
| block | mynethersdelight:powdery_button | 烟药竹按钮 | Powdery Button | #1 | #1 | #1 |
| block | abnormals_delight:aspen_cabinet | 白杨木厨柜 | Aspen Cabinet | #1 | #1 | #1 |
| block | biomesoplenty:stripped_jacaranda_log | 去皮蓝花楹原木 | Stripped Jacaranda Log | #1 | #1 | #1 |
| block | aether:icestone | 冰石 | Icestone | #1 | #1 | #1 |
| block | armourers_workshop:skin-cube-glass-glowing | 玻璃造型方块 (发光) | Glass Skin Cube (Glowing) | #1 | #1 | #1 |
| block | supplementaries:stone_tile | 石瓦 | Stone Tiles | #2 | #2 | #1 |
| block | quark:yellow_shingles_slab | 黄色陶瓦砖瓦台阶 | Yellow Terracotta Shingle Slab | #1 | #1 | #1 |

**命中率：中文 18/20（90%）｜英文 18/20（90%）｜完整 id 20/20（100%）**；有名字的 18 条里 18/18 命中、17 条在首位。

### 7.3 补一组"有名字才抽"的对照（Farming，20 条可 give 且有中文）

**中文 20/20、英文 20/20、id 20/20 命中；首位 17/20**，3 条非首位全是重名（`锅碗瓢盆` 命中 6 条、`石英柱` 3 条、`梭梭木活板门` 2 条）—— 是"同名多物"的排序问题，不是查不到。

**结论：查询链路不是瓶颈，瓶颈 100% 是名字覆盖。** 有英文名而没中文名的（wallpapers、bf_blockpack）正好对应"模组只带 en_us"。

---

## 8. 指标 6：覆盖率缺口 Top 10

### 8.1 完全没有中文的命名空间（按 id 数排序）

Farming 共 **89 个命名空间、4,179 条 id 一条中文都没有**（占全量 10.6%，占全部缺失 16,299 条的 25.6%）：

| ns | id | 可 give | jar en 键 | jar zh 键 | CFPA 键/命中 | 判定 |
|---|---|---|---|---|---|---|
| bf_blockpack | 1,203 | 1,202 | 1,433 | 0 | 0 / 0 | 模组本身没带 zh_cn（只有 en_us），CFPA 也没收 |
| cluttered | 1,031 | 1,001 | 1,062 | 0 | 0 / 0 | 同上 |
| paintable | 999 | 933 | 968 | 0 | 0 / 0 | 同上 |
| wallpapers | 154 | 134 | 190 | 0 | 0 / 0 | 同上 |
| silentgems | 80 | 80 | 0 | 0 | 47 / 0 | 无 jar（交叉引用 id，本服没装） |
| ars_nouveau | 60 | 60 | 0 | 0 | 9 / 0 | 有 assets 但无任何语言文件（只带了兼容资源） |
| waxed | 50 | 0 | 0 | 0 | 0 / 0 | 无 jar（交叉引用 id） |
| miners_delight | 38 | 38 | 0 | 0 | 0 / 0 | 无 jar（交叉引用 id） |
| nirvana | 34 | 0 | 0 | 0 | 16 / 0 | 无 jar（交叉引用 id） |
| iceandfire | 31 | 31 | 0 | 0 | 0 / 0 | 无 jar（交叉引用 id） |

zyjd 共 **30 个命名空间、241 条 id** 零中文：fetzisdisplays 100（只有 en_us）、geckolib 28（只有 en_us）、alexsdelight 23（只有 en_us）、notsoshrimple 15、endergetic 12（无 jar）、ultimatespawners 12、tactical_imbuements 9、citadel 6、goblintraders 4、dungeons_gear 3。另有 invincible / mantle 两个"jar 里有 zh_cn 但键指向别的命名空间"的情况（见 8.3）。

**判定口径**：`assets` 为 0 → 本服没装这个 mod，id 是别的 mod 的 tag/recipe 引出来的；`zh_files=0 且 en_files>0` → 模组自己只写了英文；`zh_files>0` → 见 8.3 的 key 级归因。

### 8.2 缺失条数最多的 10 个（含"只翻译了一部分"）

Farming：

| ns | id | 已有中文 | 缺失 | jar zh 键 | 判定 |
|---|---|---|---|---|---|
| yuushya | 6,080 | 1,592 | 4,488 | 2,272 | 模组自带中文不全（只翻了 26%，且 CFPA 完全没收录 yuushya） |
| farmingtales | 3,771 | 2,171（jar 702 + kubejs 1,469） | 1,600 | 702 | 模组自带中文不全；缺的部分是动态方块 |
| bf_blockpack | 1,203 | 0 | 1,203 | 0 | 模组本身没带中文 |
| cluttered | 1,031 | 0 | 1,031 | 0 | 模组本身没带中文 |
| paintable | 999 | 0 | 999 | 0 | 模组本身没带中文 |
| kaleidoscope_doll | 704 | 9 | 695 | 12 | 模组只翻了 12 个键（99% 无中文） |
| ordertocook_chair_compat | 453 | 1 | 452 | 2 | 数据驱动联动物品，模组只有 2 个 en_us 键 |
| natures_spirit | 1,184 | 754 | 430 | 729 | 模组自带中文不全（64%） |
| spawn | 352 | 61 | 291 | 0 | 模组只有 en_us（947 键），CFPA 补了 48 条 |
| bountifulfares | 599 | 334 | 265 | 475 | 模组自带中文不全（56%） |
| refinedstorage | 346 | 95 | 251 | 100 | 模组自带中文不全（27%） |

zyjd（缺失最多）：aether 651/338（中文 313，48%）、quark 1,059/162（85%）、irons_spellbooks 430/109（75%）、fetzisdisplays 100/100（只有 en_us）、block_factorys_bosses 167/81、supplementaries 369/75、cataclysm 419/43、explorerscompass 39/38（jar 只有 1 个 zh 键）、farmersdelight 219/36、naturescompass 32/31（jar 只有 1 个 zh 键）。

### 8.3 是"模组没带中文"还是"我们没解析出来"——证据

对 Top15 里**真有 zh_cn 文件**的命名空间做 key 级归因（键 → 已扫 id 的映射率）：

| ns | jar zh 键（注册类） | 映射到已扫 id | 率 | 没对上的键是什么 |
|---|---|---|---|---|
| yuushya | 2,272 | 2,267 | 100% | 5 条是 `item.get_entity_item.tooltipN` 子键 |
| farmingtales | 702 | 702 | 100% | — |
| natures_spirit | 729 | 729 | 100% | — |
| quark | 933 | 929 | 100% | 4 条药水变体（`item.minecraft.potion.effect.quark.*`） |
| refinedstorage | 100 | 100 | 100% | — |
| youkaisfeasts | 361 | 361 | 100% | — |
| storagedrawers | 123 | 123 | 100% | — |
| bountifulfares | 475 | 335 | 71% | 140 条是别的命名空间的键（`block.appledog.*`、`block.arts_and_crafts.*`，即 lang 全局合并 + 未安装 mod） |
| supplementaries | 322 | 306 | 95% | 16 条 `block.minecraft.banner.*` 子键 |
| epicfight（zyjd） | 51 | 32 | 63% | 19 条药水变体 |

**结论：只要是本命名空间自己的 id，我们的映射率是 93~100%；对不上的键基本都是①别的命名空间的键（本服没装那个 mod）②药水/banner/tooltip 子键。** 所以缺口的真实原因排序是：**模组没翻译（主因）> 数据驱动/状态变体 id 天然没名字 > 我们没解析出来（可忽略）**。唯一真正的"我们看不到"是 EveryCompat / chipped 这类运行时动态生成方块的 mod（CFPA 有 3,141 条 everycomp 键，静态扫描一条 id 都还原不出来）。

---

## 9. 与 research/05 的差异

| 指标 | 05 | 本次 | 说明 |
|---|---|---|---|
| Farming id 总数 / 有中文 | 39,585 / 22,769（57.5%） | **完全相同** | 口径 = jar + kubejs 资源包 |
| Farming give 可用 / 其中带中文 | 32,152 / 17,517（54.5%） | **完全相同** | 05 没写规则，复现出来必须再加"kinds 不含 entity/fluid"这一条（见 1.3） |
| zyjd 四个数 | 8,974 / 5,959 / 7,213 / 4,984 | **完全相同** | — |
| Farming 有英文 | 26,776 | 22,481（jar）/ 26,776（含 trans） | 05 把 `english_translation.json` 的别名也算作英文；本文把 trans 单列，因为它只是英文别名表，不是翻译层 |
| Farming ns 有 en_us / zh_cn | 207 / 155 | **221 / 167** | 05 只数顶层 jar；含 jar-in-jar 递归是 221/167，**no-nested 复算正好 207/155**，差异纯属递归深度 |
| zyjd ns 有 en_us / zh_cn | 139 / 102 | **149 / 109** | 同上（no-nested 复算 = 139/102） |
| Farming 无任何名字 | 12,809 | 12,809（不含 CFPA）/ **12,410**（含 CFPA） | 差额 399 = CFPA 补了中文但仍无英文的 id |
| Farming kubejs_lang 贡献 | "10,225 条 id 的中文来自这里" | 覆盖 **10,224** 条 id（6,835 独有 + 3,389 与 jar 重叠） | 差 1 条：有 1 个 kubejs 键的 value 是空串（资源包"抹掉名字"的写法），只产生 id 不产生名字 |
| Farming "lang" 信源 | 22,807 | 中 15,934 / 英 22,481 | 05 的 22,807 是"被 jar lang 触及的 id 数"，包含 228 条只被子键触及、最终没名字的 id；本文按"确实拿到名字"拆开报，不能直接对比 |
| 原版有中文 | "约 199 个" | **164（Farming）/ 3（zyjd）** | 05 未写口径与来源；本文按"静态扫描 + jar/kubejs/CFPA 三层"实测。若加上 research/07 的内置原版表，这两个数会变成 1,460 / 1,090 |
| Farming CFPA 增益 | 未测 | +517 条（+1.3pp，相对 jar+kubejs）/ +3,122（+7.8pp，相对 jar） | 本轮新增 |

**没有矛盾的项**：05 的"kubejs 资源包 10,225 条"、"Farming 175 个 zh 文件"（本次原型统计 `lang_file_zh_cn=175`）都对上了。**唯一需要提醒后来人的**是 05 的 give 可用口径没写全（少了"不含 entity/fluid"），照抄会差 5/13 条。

---

## 10. 给实现的硬结论

1. **scanner 必须同时扫 `kubejs/assets/*/lang/zh_cn.json`**（8 个文件、23,826 键、约 0 成本）。Farming 靠它从 48.1% 涨到 58.8%；不扫这一层，CFPA 的全部价值只有 +1.3pp，"有可量化提升"这条验收会很难看。
2. **原版不内置常量表，改用服务端 en_us + 外部 zh_cn**（research/07 定案；本文此条原写"必须内置"已作废）。CFPA 里没有原版键（3,270 条 minecraft.* 键实测 0 命中），jar 里也没有（0 个 jar 提供 assets/minecraft/lang），但 Forge 的 `server-<ver>-extra.jar` 自带官方 en_us（1,369 条 ID + 英文名，离线 0.11 s），中文取官方 zh_cn（客户端 assets / 服主手放 / 按版本下载）且只当字典。不做的话，`minecraft:diamond_sword` 这种最常用的物品永远查不到中文。
3. **CFPA 合并要按 1.4 的顺序过滤**，并且**只对已扫 id 生效**；不要把 CFPA 的 74,559 条未匹配键拿去新增 id（会把 477 个没装的 mod 灌进库，悬空 25 万条幽灵行）。同时注意 CFPA 的 +517 里有 269 条落在"交叉引用 id"上，统计回执里最好把这类 id 单列，避免服主误以为游戏里真多了 500 个中文物品。
4. **别把 `has_item` 口径写成"含 item 即算"**，否则统计和 05 对不上；按 1.3 的互斥口径，回执数字才是可比的。

---

## 11. PRD 验收标准建议

### 11.1 建议条文（可直接替换 prd.md 里那条模糊标准）

> **中文覆盖率（实测基线，分母 = 知识库还原出的全部 id，含原版但原版单列）**
> - Farming（278 mods）：全量 id 中文覆盖率 **≥ 55%**（实测 58.8%）、give 可用子集 **≥ 52%**（实测 56.0%）；
> - zyjd（228 mods）：全量 id 中文覆盖率 **≥ 67%**（实测 71.0%）、give 可用子集 **≥ 68%**（实测 73.1%）；
> - 合并 CFPA 后，全量中文覆盖率相对"仅 jar 自带翻译"至少提升 **3 个百分点**（实测 Farming +7.8pp、zyjd +4.6pp）。
> - 原版（`minecraft:` 命名空间）不计入上述门槛，单独验收：**Farming 1,460 条 / zyjd 1,090 条原版 id 中，1,369 条 item/block 由服务端 en_us 提供 ID + 英文名，中文由外部 zh_cn 补齐**（当前实测中文 11.2% / 0.3%，缺口即为此项的依据）。

### 11.2 门槛留了多少余量、为什么可靠

| 门槛 | 实测 | 余量 | 余量能吃下什么 |
|---|---|---|---|
| Farming 全量 ≥55% | 58.8% | **3.8pp（约 1,500 条 id）** | CFPA 快照删掉一半新增（-0.7pp）、换成"只含 CJK 才算"的严格口径（-0.2pp）、分母里多算/少算幽灵 id（±0.3pp） |
| Farming give ≥52% | 56.0% | **4.0pp** | give 口径换成"含 item 即算"会 **涨**到 57.3%，不会跌破 |
| zyjd 全量 ≥67% | 71.0% | **4.0pp** | zyjd 没有 kubejs 层，数字最"干净"，只受 CFPA 快照影响（CFPA 单独贡献 4.6pp，砍掉 1/4 才跌破） |
| zyjd give ≥68% | 73.1% | **5.1pp** | 换成宽松 give 口径是 71.2%，仍在门槛上 |

为什么"现实中可靠、不是吹的"：

- 这两个数是**真实服务器 + 真实 CFPA 快照**跑出来的，不是估算；扫描是确定性的（同一输入重复跑得到同一组数，本轮已验证两次）。
- 余量 ≥3.8pp，正好覆盖"实现比原型少合并一个信源"这种最常见的偏差（丢掉 model/blockstate 会让分母少约 2~3%）。而**能跌破门槛的实现只有一种**：没扫 kubejs 资源包（Farming 会掉到 48.1%）—— 这正是我们想用门槛挡住的。
- 天花板是客观的：Farming 有 89 个命名空间、4,179 条 id **在任何现有翻译源里都没有中文**（bf_blockpack/cluttered/paintable 三家就 3,233 条），yuushya 6,080 条里 CFPA 一条都没收。所以 58.8% 已经接近"只用权威翻译"的物理上限，写 55% 既不会逼出造假，也没有写成 80% 那种做不到的数。

### 11.3 什么情况下这套门槛不适用

- **实现明确不读 kubejs 资源包**（PRD 只写"扫 mods/*.jar"）：Farming 只能到 48.1% / give 47.9%，此时 Farming 门槛必须降为 **≥45%（全量）/ ≥44%（give）**；zyjd 不受影响（无 kubejs 层），仍按 67% / 68%。
- **服务器换了整合包 / 大批更新 mod**：分母和可翻译集合都会变，这套数字只在 Farming、zyjd 当前快照上成立。验收请在**这两台服的当前状态**上跑，不要拿它当通用门槛。
- **一期同时接入原版**（research/07：服务端 en_us + 外部 zh_cn）：会额外 +3.3pp（Farming）/ +12.1pp（zyjd），门槛只升不降，可以照旧用。
