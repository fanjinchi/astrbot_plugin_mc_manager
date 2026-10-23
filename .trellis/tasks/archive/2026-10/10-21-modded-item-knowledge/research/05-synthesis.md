# MC 模组服「物品 / 翻译 / 配方」认知能力 —— 研究报告（汇总）

> 研究任务：让 AstrBot 的 MC 管理插件（astrbot_plugin_mc_manager）能认识一个 Forge 整合包服务器里有哪些物品、叫什么、怎么合成。
> 分报告：`01-static-item-extraction.md`（静态物品/翻译）、`02-runtime-dump.md`（运行时 dump）、`03-recipes-and-jei.md`（配方与 JEI）。
> 测试环境：/home/guigui/mc/Farming（MC 1.20.1 Forge 47.4.20，278 mods）与 /home/guigui/mc/zyjd（1.20.1 Forge 47.4.0，228 mods）。原始目录全程只读。

---

## 0. 一句话结论

**这件事完全做得到，但不是「给 LLM 一个命令」，而是「离线建一个知识库 + 给 LLM 两三个检索工具」。**
物品 id 用运行时注册表 dump 拿（权威），中文名用 jar 里的 zh_cn.json 拿（唯一来源，实测命中 69.4%），配方两条路都能拿到：静态扫 data/*/recipes/*.json 覆盖 91~185 种类型，运行时脚本 dump 覆盖 93% 配方条数且带 tag。三者按 id join 成 SQLite，插件启动加载，LLM 只做检索、不背全书。

---

## 1. 插件现状的三个硬伤（代码实锤）

| 位置 | 问题 | 后果 |
|---|---|---|
| tools/game_tools.py:47 | give_item 无条件补 minecraft: 前缀 | 玩家要模组物品必失败 |
| tools/world_tools.py summon_entity | 同样无条件补前缀 | 模组生物无法召唤 |
| tools/game_tools.py clear_inventory | 同上 | 无法定向清除模组物品 |

且 30 个 llm_tool 全部只描述原版命令，LLM 对整合包内容零认知 —— 这是「玩家要东西 AI 不知道」的根因，不是模型能力问题。

---

## 2. 问题一：物品 ID + 翻译怎么拿

### 2.1 三条信源，各有不可替代的作用

| 信源 | 能拿到 | 拿不到 | 实测 |
|---|---|---|---|
| 运行时注册表 dump | 权威 id 全集、tkey（语言键）、英文显示名、kind | 中文名、配方 | zyjd: item 6759 / block 4247 / entity 931 / fluid 44 |
| jar 内 assets/*/lang/zh_cn.json | 中文名 | 存在性（有幽灵 key） | Farming 175 个 zh 文件；zyjd 113 个 |
| kubejs/assets/*/lang/*.json（资源包层） | 中文名（游戏里最后生效） | — | Farming 10,225 条 id 的中文来自这里 |

**关键洞察**：lang 文件是**全局合并**的，文件放在哪个 namespace 目录**不影响** key 解析。
实证：`Farming/kubejs/assets/minecraft/lang/zh_cn.json`（15,910 条）里有 dramaticdoors 2189 条、dustydecorations 533 条 —— id 的 namespace 必须取 **key 的第二段**，取文件名目录会把 1,117 个 key 判错。

### 2.2 运行时怎么拿（两条路，都不需要写服务端 mod）

**路 A：KubeJS 内置命令（最省事）**

```
kubejs dump_registry minecraft:item              -> 纯文本列表，205,893 字符
kubejs dump_registry minecraft:entity_type       -> 24,671 字符
kubejs dump_registry minecraft:recipe_serializer -> 3,285 字符
forge tags minecraft:item get forge:ingots/iron  -> 矿物词典查询
forge mods                                       -> 模组列表（含中文名）
kubejs export                                    -> 落盘 registries/ tags/ loot_tables/ mods.json
```

前提：服务器装了 KubeJS（当前两个服都有），RCON 控制台天然是 4 级权限。

**路 B：丢一个 KubeJS 脚本（拿到的东西更多）**
在 kubejs/server_scripts/ 放一个脚本注册 /researchdump，遍历 BuiltInRegistries + server.recipeManager 输出 JSONL：

```
item.jsonl    6759 行  {"id":"abnormals_delight:adzuki_cake_slice",
                        "tkey":"item.abnormals_delight.adzuki_cake_slice",
                        "resolved":"Slice of Adzuki Cake","stack":"{Count:1b,id:...}"}
block.jsonl   4247 行
entity.jsonl   931 行
fluid.jsonl     44 行
recipe.jsonl  6231 行  <- 5805 条 inputs+outputs 齐全（必须用 Ingredient.toJson()）
```

**路 B 的独特价值**：tkey 直接告诉你该查 item. 还是 block. 前缀（BlockItem 的键是 block.*）；resolved 是服务端实际生效的英文名（比解析 en_us 更准，能反映 mod 运行时改名）；配方能拿到 93.2%（输入输出齐全，tag 原样保留）。

**实测踩坑**：配方输入必须用 Ingredient.toJson()，用 Ingredient.getItems() 在 KubeJS 桥接下只会返回空数组（22,190 个槽全空）；recipe.getType() 直接 String 化得到 null，要取 ResourceKey 再拼。

### 2.3 静态怎么拿（jar 扫描）

规则极简：kind.namespace.path，id = namespace:path，kind 属于 {item, block, entity, fluid}。

实测准确率（Farming 47,209 个注册类 key）：**93.8% 能命中独立证据**（tag/recipe/loot/model/blockstate 里也出现），仅 6.2% 纯靠猜；幽灵 key 上界 2.3%。

**三个必须防的坑（都实测出来了）**：

1. **子 key 污染（最危险）**：item.minecraft.potion.effect.stability 会把 minecraft:potion 命名成「稳定药水」。Farming 有 6,452 个四段以上 key，占 13.7%，必须判为子 key 丢弃。修掉后 yuushya:a_acacia_blindwall 从错误占位符「§9[模板材料]」恢复为正确的「金合欢木板壁 A」。
2. **模型目录不是物品**：models/item/template/*.json 会产生 3,053 条假 id，path 带 / 的一律丢弃（真实注册名本包内 0 例带 /）。
3. **jar 的 modId 不等于它提供的 assets namespace**：framework-1.0.2.jar 的 modId 是 standalone_copycats，却提供 assets/farmingtales/**（3,772 条 id 拿不到 mod 名）。

### 2.4 真实数字

| | Farming | zyjd |
|---|---|---|
| jar（含 jar-in-jar 递归） | 278 -> 378 | 228 -> 322 |
| mods.toml 解析出 mod | 310 | 243 |
| **还原出的 id 总数** | **39,585** | **8,974** |
| 有中文 | **22,769（57.5%）** | **5,959（66.4%）** |
| 有英文 | 26,776 | 6,590 |
| give 可用（item + 带模型 block） | 32,152 | 7,213 |
| 其中带中文 | 17,517（54.5%） | 4,984（69.1%） |

信源贡献（Farming，同一 id 可多源）：model 27,394、blockstate 23,101、tag 22,888、lang 22,807、recipe 21,272、loot 21,003、trans 10,633、kubejs_lang 10,225、script 6,399。
-> **只看 lang 会漏 42.4%（16,778 条）真实注册名**，必须多信源合并。

### 2.5 中文覆盖率的真相：不是方法问题，是模组就不带中文

- Farming：207 个 namespace 有 en_us，只有 155 个有 zh_cn（53 个纯英文：bf_blockpack 1203、cluttered 1031、paintable 999...）
- zyjd：139 有 en_us vs 102 有 zh_cn
- **最大硬伤是原版（已更正，见 research/07）**：服务端安装里没有 client jar，扫描出的 1,088~1,298 个 minecraft: id 里只有约 199 个有中文，minecraft:diamond_sword 这种最常用的反而查不到。
  -> 但 Forge 的 `libraries/net/minecraft/server/*/server-<ver>-extra.jar` 里**自带官方 en_us.json**（386,499 B / 6,217 条），可离线还原 1,369 个原版 ID + 英文名（精度 100%、召回 97.6%、耗时 0.11 s）；中文只需 385 KB 的官方 zh_cn.json（运行时下载或服主自备）。
  -> **不需要内置常量表**；早期"必须内置"的结论作废（内置还违反 Mojang EULA 的再分发限制）。

已排除的两个假线索：
- Farming/hotai/ **不是**翻译覆盖，是 ModLauncher ITransformationService + org.badiff 二进制类补丁（79 个 .badiff、245KB，strings 与 grep -P '\p{Han}' 全空）。
- kubejs/config/english_translation.json **只有英文**（registry 段 13,698 条 key->英文），和 jar en_us 高度重合（trans 与 kubejs_lang 交集 10,225/10,225）。

---

## 3. 问题二：配方怎么查、怎么理解

### 3.1 JEI 到底是怎么做到的（源码级，clone 了 1.20.1 分支）

| 环节 | 事实 | 证据 |
|---|---|---|
| 配方存哪 | 服务端 datapack data/<ns>/recipes/**.json | 扫描结果 |
| 怎么到客户端 | 登录时原版 ClientboundUpdateRecipesPacket 全量下发 | Fabric/.../ClientPacketListenerRecipeUpdateMixin.java:22-31 |
| 客户端怎么解析 | 用**客户端自己注册的** RecipeSerializer 反序列化进 RecipeManager | — |
| JEI 怎么取 | RecipesUpdatedEvent 里 Internal.setClientSyncedRecipes(...) | Forge/.../JustEnoughItemsClient.java:109-112 |
| mod 怎么进 JEI | 必须主动 @JeiPlugin -> registerRecipes().addRecipes(RecipeType<T>, List<T>) | IRecipeRegistration.java:49 |

-> **「客户端不装 mod 就查不到配方」不是 JEI 的策略，是缺 serializer 就反序列化不出来**。JEI 自己的注释承认兜底数据「不含服务端 datapack / 服务端 mod 配方」（VanillaClientRecipeLoader.java:23-29）。

两个常见误解纠正：
- 1.20.1（JEI 15.49）**已没有 IRecipeWrapper**（jar 里 grep 零命中），配方对象就是 T。
- JEI **没有官方 dump**：源码 grep dump 零命中，唯一 /jei 命令是 /jei_internal_show <link>（聊天物品链接用）。

**唯一静态拿不到的东西是 catalyst**（「哪台机器能做这类配方」），它只在代码 addRecipeCatalysts() 里。这是运行时路线不可替代的价值。

### 3.2 静态扫描的真实覆盖

| | Farming | zyjd |
|---|---|---|
| 配方 JSON 文件 | 29,296 | 6,648 |
| recipe type 种类 | **185** | **91** |
| 拆 forge:conditional 后叶子 | 29,027 | 6,722 |
| 剔除「混进来的数据表」 | -597 | -49 |
| **可显示配方** | **28,430** | **6,671** |
| 死配方（mod 没装） | 24 | **96**（其中 create:* 71 条 —— zyjd 根本没装机械动力） |
| 灌进 SQLite | 28,042 | 6,242 |

**交叉验证**：zyjd 静态灌库 6,242 条 vs 运行时 server.recipeManager 实测 6,231 条 —— **差 11 条（0.18%）**，说明静态扫描基本无遗漏。

**但两者质量不同**：静态能见 91 种类型；运行时只覆盖 35 种（稀有类型归到 null），却覆盖 93% 的配方**条数**，且 5,805/6,231 输入输出齐全、22,190 个输入槽里 3,587 个是 tag。静态的优势是类型全 + 有嵌套结构；运行时的优势是反映 KubeJS 增删和 conditional 求值后的真实状态。

top30 类型已覆盖 95.1%（Farming）/ 98.1%（zyjd）的配方 -> 机器映射表只需手写约 30 条。

### 3.3 六个实测陷阱

1. **recipes/ 目录里混着不是配方的东西**：crockpot:food_values（营养值表，Farming 528 条）、aether:*_placement_ban（放置黑名单）、quark:mixed_exclusion、jeed:effect_provider（JEI 信息页伪配方）。共 597 条，不过滤 AI 会说「苹果可以通过 FRUIT 配方获得」。
2. **forge:conditional 是包装器**：Farming 1,850 / zyjd 1,032。里面 {"type":"forge:false"} 表示**配方被作者显式禁用**（zyjd 60 条、Farming 1 条）。条件类型以 mod_loaded(609)、*:config(430/284)、item_exists(601) 为主，静态只能判一部分。
3. **KubeJS 动态增删（静态无解）**：Farming 135 个 server_scripts、event.add 194 次 / **event.remove 121 次**。静态库会留下最多 121 条幽灵配方，AI 会教玩家做一个已经被删掉的配方。zyjd 只有 1 个脚本，影响可忽略。
4. **result 有 4 种键名**（result 23,824 / results 2,940 / output 111 / outputs 27），且 8 类配方输出不在标准键里：meadow:woodcutting 用 outputItem；aether:repairing 输出=输入本身；apotheosis:salvaging 输出套在 stack 里；kaleidoscope_tavern:pressing_tub 输出是流体；touhou_little_maid:altar_crafting 输出 id 埋在 NBT 里。
5. **tag 输入不展开就等于没回答**：Farming 输入槽里 17.5% 是 tag（如 create:crushing 吃 forge:ores/aluminum）。玩家问「铝矿石怎么粉碎」不展开就匹配不上。纯静态可解（扫 data/**/tags/items 并递归展开），**建议第一版就做**。
6. **上下文爆炸是必然会发生的**：minecraft:stick 作为输入有 **1,345** 条配方、iron_ingot 406 条、chest 239 条。必须 LIMIT 8~10 + 分组聚合（「共 406 条，涉及 12 类机器，这里每类给 2 条」）。

### 3.4 数据模型（已实测灌库 34,284 条配方 / 94,809 输入槽 / 35,657 输出槽）

核心是**槽位表**而不是塞 JSON 数组，才能建倒排索引：

```sql
recipe(id, pack, recipe_id, recipe_type, source_jar, time_ticks, xp, energy,
       conditional, raw_json)                       -- raw_json 兜底未解析类型
recipe_input(recipe_pk, slot, role,                 -- role: input|tool|container
             kind, ref, count)                      -- kind: item|tag|fluid
recipe_output(recipe_pk, slot, kind, ref, count_min, count_max, chance)
item_name(id, kind, name_zh, name_en, mod_name, confidence)
item_alias(alias, item_id)                          -- 口语别名表
item_tag(tag, item_id)                              -- tag 展开缓存
recipe_category(type, machine, label_zh, source)    -- 复合主键：一类多机器
```

schema 实测覆盖：按条数 **99.2%（Farming）/ 95.9%（zyjd）**；按类型只有 69%/57%，但掉队类型只占 **0.76%/4.14%** 的配方 -> **不值得给 185 个类型逐个写解析器，只手写 5 个 adapter**（create:sequenced_assembly、meadow:woodcutting、apotheosis:salvaging、kaleidoscope_tavern:pressing_tub、touhou_little_maid:altar_crafting），其余进 raw_json。

### 3.5 中文 -> id 的匹配：子串就够，别上向量

实测：苹果酒 -> 3 命中、卷心菜 -> 11 命中（方块 vs 物品各一个）、坩埚 -> 0 命中（该 mod 没中文名）。997 个中文名对应多于 1 个 id。

排序键：(名字不等于查询, len(名字), kind) —— 精确名优先，长的优先。补几十到几百条口语别名表（「工作台」-> crafting_table）。**不要拼音、不要向量**：向量会把「苹果酒」召回「苹果汁」，对配方查询是负收益。

---

## 4. 推荐架构：运行时校准 + 静态知识库 + 检索工具

```
[服务端 mods/*.jar]  --+-- lang zh_cn/en_us   --> 中文名/英文名
                       +-- data/*/recipes/**  --> 配方（槽位化）
                       +-- data/*/tags/item/**--> 矿物词典
                       +-- models/item/*.json --> 存在性/可否 give

[可选] 运行时 dump（KubeJS 脚本 /researchdump）
        --> 权威 id 全集 + tkey + 英文显示名 + 93% 配方   <- override 层

[内置] 原版 1.20.1 zh_cn.json（约 6000 条常量）
                       |
                 knowledge.sqlite   (Farming 17.4MB / gzip 2.7MB)

插件启动加载（不要在事件循环主线程同步扫 716M）
玩家提问 -> LLM -> search_item / get_recipes -> SQLite -> top-N 摘要
```

**为什么必须分层**：
- 纯静态：会教玩家做已被 KubeJS 删掉的配方、说错机器、原版物品没中文名、有 2~3% 幽灵 key。
- 纯运行时：拿不到中文名（只能 join）、配方类型只覆盖 35/91、快照会过期、需要服主配合跑一次。
- **运行时给「存在性与当前状态的权威性」，静态给「中文名、全类型配方、原版常量」，join 起来才完整。**

### 建议的 LLM 工具面（只加 2~3 个，免权限，只读）

| 工具 | 签名 | 返回 |
|---|---|---|
| search_item | (keyword, mod=None, limit=10) | [{id, name_zh, name_en, mod_name, kind, confidence}] |
| get_recipes | (item_or_id, direction=howto/uses, limit=8) | 分组后的配方摘要（type + 机器中文名 + 关键输入 + 输出，含概率） |
| get_item_tags | (item_or_id) | 该物品所属标签 / 该标签下的物品 |

give_item / summon_entity 内部先调 search_item 解析，再执行。

### 必须改的执行逻辑（game_tools.py）

```
1. 输入已含 ':'  -> 原样透传（修掉硬编码 minecraft:）
2. 否则查库：精确 id -> 中文精确名 -> 英文精确名 -> FTS 子串
3. 命中 1 条 -> 用该 id；命中多条 -> 把候选返回给 LLM 让它追问
4. 查不到 -> 回退旧行为并在返回值里明确标注「这是猜测」
5. give 失败 -> 把 RCON 报错原文回传给 AI（避免它反复重试同一个错误 id）
```

---

## 5. 落地路线建议

**阶段 1（最小可用，1~2 天）**
1. 独立 CLI：扫 mods/ -> 生成 knowledge.sqlite（可复用 .research/prototype/scan_items.py 与 .research/artifacts/load_sqlite.py）
2. 内置原版 zh_cn.json 常量表
3. 新增 search_item 工具 + 修掉四处硬编码前缀（含 fill_blocks）
4. 配置项：知识库路径、是否启用

**阶段 2（配方）**
5. 配方灌库 + get_recipes 工具，LIMIT 8 + 分组聚合
6. tag 递归展开

**阶段 3（可选，运行时校准）**
7. 提供一个可选 KubeJS 脚本（/researchdump）或直接用 kubejs dump_registry，把权威 id + tkey 作为 override 层
8. 管理命令重建知识库（后台线程）

---

## 6. 剩余风险（务实排序）

| 风险 | 现实影响 | 建议 |
|---|---|---|
| 中文名覆盖只有 55~70% | 冷门物品可能只回英文名 | 可接受（游戏内本来也是英文）；配人工补译表 |
| KubeJS 删改配方（Farming 121 条） | 极少数情况给出过时配方 | 加一句「以游戏内 JEI 为准」；或上阶段 3 校准 |
| 物品名缺失/一名多物（997 例） | 可能给错物品 | 返回候选让 LLM 追问，别静默取第一个 |
| 配方上下文爆炸（stick 1345 条） | 爆 token | 硬 LIMIT + 分组，已设计 |
| 运行时方案依赖 KubeJS | 没装 KubeJS 的服拿不到权威表 | 静态扫描兜底，覆盖 93.8% |
| 运行时配方类型只有 35/91 | 稀有机器类配方可能查不到 | 静态 JSON 补；或对 top30 类型做 adapter |
| 启动时全量扫描阻塞事件循环 | 卡住 AstrBot | 放后台任务/线程池，别在主线程做 |

---

## 7. 待与用户确认的关键决策

1. **数据来源**：纯离线扫 jar（零服务端依赖）／运行时 dump（权威但要装 KubeJS）／两者结合（推荐）
2. **构建时机**：随插件分发预构建库？服主手动跑 CLI？插件启动后台构建？
3. **配方深度**：「能查」就够，还是要「理解」（判断材料够不够、模拟合成步骤）？
4. **中文补充**：是否要支持服主提供额外汉化资源包/补译表？
5. **工具权限**：查询类工具是否免权限（建议免权限，只读）

---

## 附录：产物清单

| 路径 | 内容 |
|---|---|
| .research/01-static-item-extraction.md | 静态提取完整报告（433 行） |
| .research/03-recipes-and-jei.md | 配方与 JEI 完整报告（648 行） |
| .research/02-runtime-dump.md | 运行时 dump 报告 |
| .research/prototype/scan_items.py | 物品/翻译扫描器（716 行，纯标准库，Farming 6.9s/171MB） |
| /tmp/mcresearch/out/{farming,zyjd}.sqlite | 扫描产物（Farming 17.4MB，gzip 后 2.7MB） |
| .research/artifacts/scan_recipes.py | 配方扫描器（约 40s） |
| .research/artifacts/load_sqlite.py | 配方 schema + 通用抽取器 + 灌库 |
| .research/raw/ | 运行时命令原始返回（含 kubejs dump_registry 全量输出） |
| /tmp/mc-rd/zyjd/kubejs/server_scripts/zz_research_dump.js | 运行时 dump 脚本原型 |
| /tmp/mc-rd/dump/*.jsonl | 运行时 dump 产物（item 6759 / block 4247 / entity 931 / recipe 6231） |
