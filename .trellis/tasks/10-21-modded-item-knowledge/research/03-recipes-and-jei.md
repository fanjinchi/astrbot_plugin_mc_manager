# 03 · 配方查询与理解：JEI 是怎么做到的，我们离线能还原多少

> 研究范围：仅研究，不写插件代码。所有实测在 /home/guigui/mc/Farming（278 jar / 716M）与 /home/guigui/mc/zyjd（228 jar / 977M）上完成；
> 两个整合包目录全程只读，工作产物全部落在 /tmp 与 /home/guigui/mc/.research/。
> 环境：Java 17（zulu17.60.16）/ python3.12；服务器未启动，本文结论全部来自**静态扫描 + 源码阅读**，不含运行时 dump（那条线由另一位同事实测）。

---

## 结论速览

1. **JEI 是纯客户端 mod，它不“生产”配方，只是“读别人给它的东西”**。配方 JSON 在服务端 datapack（`data/<ns>/recipes/*.json`），登录时由原版 `ClientboundUpdateRecipesPacket` 下发，客户端用**自己的** `RecipeSerializer` 反序列化成 `Recipe` 对象塞进客户端 `RecipeManager`；JEI 在 `RecipesUpdatedEvent` 里把这份列表抄走（`Forge/src/main/java/mezz/jei/forge/JustEnoughItemsClient.java:111`）。所以“客户端必须装对应 mod”不是 JEI 的策略，是**没有 mod 就没有反序列化器**。
2. **每个 mod 必须主动注册**：在自己的 `JeiPlugin` 注解里 `registerRecipes(IRecipeRegistration)` → `addRecipes(RecipeType<T>, List<T>)`。JEI 不会遍历 `RecipeManager` 自动发现 mod 配方类型。
3. **1.20.1 已经没有 `IRecipeWrapper` 了**（顺手纠正一个常见误解）：`jei-1.20.1-forge-15.49.0.191.jar` 里 `mezz/jei/api/**` 共 191 个类，grep `RecipeWrapper` **零命中**；配方对象本身就是 `T`，由 `IRecipeCategory<T>` 负责画。真正还在的是 `IRecipeCategory` / `IRecipeRegistration` / `IRecipeManager`（运行时查询）/ `IRecipeCatalystRegistration`（机器）。
4. **JEI 没有官方 dump**。全源码 grep `dump` 零命中；唯一的 `/jei` 命令是 `/jei_internal_show <link>`，只用来处理聊天里的物品链接（`Common/.../chat/JeiChatItemLinks.java:22`）。想 dump 只能靠 mixin/额外 mod。
5. **两个包的真实配方量级**（静态 JSON 扫描）：
   - Farming：**29,296** 个配方文件 / **185** 种 recipe type；拆掉 `forge:conditional` 包装、剔掉非配方数据表后 **28,430** 条可显示配方；其中 **24** 条是死配方（mod 没装）。
   - zyjd：**6,648** / **91** 种；拆包装后 **6,671** 条；**96** 条死配方（`create:*` 71 条——**zyjd 根本没装机械动力**）。
6. **通用 key 猜测能装下 99.2%（Farming）/ 95.9%（zyjd）的配方**，但只覆盖 128/185 与 60/106 个**类型**；剩下 57/46 个稀有类型靠 per-type adapter，占比只有 0.76%/4.14%。结论：**先用通用抽取器 + 手工补 5 个左右的 adapter 就够，不要给 185 个类型逐个写解析**。
7. **中文匹配用“子串 + 别名表”完全够**：Farming 导出的 15,512 个物品里 14,188 个有中文名，实测 `苹果酒` → 3 命中（含精确）、`卷心菜` → 11 命中（`cabbage` 方块 vs 物品）、`坩埚` → 0 命中。不需要拼音，更不需要向量。
8. **静态扫描比 JEI 更“全”，JEI 比静态更“准”**。静态能看到所有 JSON（包括 mod 没装的、被 KubeJS 删掉之前的），但看不到运行时 `event.remove()` 的结果、看不到 tag 展开后的实际物品、看不到 catalyst（机器）。正确分工：**静态建知识库 + 运行时 dump 做“以服务端实况为准”的校验层**。

---

## 1. JEI 架构与配方来源

### 1.1 事实链：配方数据到底在哪

| 环节 | 载体 | 证据 |
|---|---|---|
| 配方定义 | 服务端 datapack：`data/<ns>/recipes/**.json`（mod jar 里的 `data/` 就是内置 datapack） | 扫描结果：Farming 29,296 个、zyjd 6,648 个 JSON |
| 服务端加载 | `RecipeManager` 按 `type` 找 `RecipeSerializer` 反序列化 | 原版机制；mod 通过 `DeferredRegister<RecipeSerializer<?>>` 注册自己的类型 |
| 下发客户端 | 原版 `ClientboundUpdateRecipesPacket`（登录/`/reload` 时全量发） | JEI Fabric 侧 mixin 直接挂在 `handleUpdateRecipes`：`Fabric/src/main/java/mezz/jei/fabric/mixin/ClientPacketListenerRecipeUpdateMixin.java:22-31` |
| 客户端接收 | client `RecipeManager`（用每个 mod 的 serializer 反序列化） | 同上 |
| JEI 取数 | Forge `RecipesUpdatedEvent` → `Internal.setClientSyncedRecipes(recipes)` | `Forge/src/main/java/mezz/jei/forge/JustEnoughItemsClient.java:109-112`：`List<Recipe<?>> recipes = List.copyOf(event.getRecipeManager().getRecipes()); Internal.setClientSyncedRecipes(recipes);` |
| 兜底 | 服务端没发配方时，JEI 读客户端 jar 内置的原版 JSON | `Common/src/main/java/mezz/jei/common/recipes/VanillaClientRecipeLoader.java:23-29` 注释原文：*“This is only a fallback for connections where the server does not send recipe data to JEI. The returned recipes do not include server datapacks or server-side modded recipes, so they may not match the recipes that are actually available on the server.”* |

**为什么“客户端也要装 mod”**：下发的只是 JSON 文本，反序列化成 `Recipe` 对象要靠客户端注册表里的 `RecipeSerializer`。缺 mod → 反序列化失败 → 该配方在客户端 `RecipeManager` 里根本不存在 → JEI 无从显示。同一份 JSON，服务端认识、客户端不认识，就是“服务器能合成但 JEI 查不到”。这不是 JEI 的选择，是原版同步机制决定的。

官方文档同结论（1.16.5–1.20.1 版页面）：
- https://github.com/mezz/JustEnoughItems/wiki/Recipes-Overview-%5BMinecraft-1.16.5-to-1.18.2%5D
  > “Register your recipes with the recipe category … calling `IRecipeRegistration.addRecipes(RECIPE_LIST, KEY)`”
- https://github.com/mezz/JustEnoughItems/wiki/Recipe-Categories-%5BMinecraft-1.16.5-to-1.18.2%5D
- https://github.com/mezz/JustEnoughItems/wiki/Creating-Plugins-%5BMinecraft-1.16.5-to-1.18.2%5D
- 仓库根：https://github.com/mezz/JustEnoughItems （本机 clone 的 `1.20.1` 分支源码即权威依据）

### 1.2 四个角色（1.20.1 实际 API）

| 角色 | 真实类（1.20.1 = JEI 15.49） | 职责 | 对我们的价值 |
|---|---|---|---|
| 分类 | `mezz.jei.api.recipe.category.IRecipeCategory<T>` | 画背景、定标题、摆槽位、`getRecipeType()` | 决定“这是哪台机器/哪个 tab” |
| 注册 | `IModPlugin.registerRecipes(IRecipeRegistration)` → `addRecipes(RecipeType<T>, List<T>)` | **mod 主动把自己的配方塞进 JEI** | 证明配方不是 JEI 自动发现的 |
| 查询 | `mezz.jei.api.recipe.IRecipeManager.createRecipeLookup(RecipeType<R>)` | 运行时按 input/output 反查（对应 `IRecipeLookup.withInput` / `withOutput`） | **正是我们要的两种问法**，JEI 自己就是这么实现的 |
| 机器 | `IRecipeCatalystRegistration.addRecipeCatalysts(RecipeType<?>, ItemLike...)` | 声明“哪些方块能出这类配方” | “有哪台机器能做 X”的唯一权威来源，**只存在于代码** |
| ~~包装~~ | ~~`IRecipeWrapper`~~ | **1.16 之后已删除**；对 jei jar 执行 `unzip -l` 后 grep RecipeWrapper 零命中 | 别照旧教程建模 |

`IRecipeRegistration.addRecipes` 的确切签名（`CommonApi/src/main/java/mezz/jei/api/registration/IRecipeRegistration.java:49`）：
~~~java
<T> void addRecipes(RecipeType<T> recipeType, List<T> recipes);
~~~
`IRecipeCatalystRegistration` 的 javadoc（同文件 `:33-43`）说得很直白：
> “Allows players to see what ingredient they need to craft in order to make recipes from a recipe category.”
> `void addRecipeCatalysts(RecipeType<?> recipeType, ItemLike... ingredients);`

### 1.3 JEI 内部索引 = 双向倒排

`Library/src/main/java/mezz/jei/library/recipes/RecipeManagerInternal.java:53`：
~~~java
private final EnumMap<RecipeIngredientRole, RecipeMap> recipeMaps;
~~~
`RecipeIngredientRole` 只有 `INPUT` / `OUTPUT` 两个值（`CommonApi/.../recipe/RecipeIngredientRole.java`），也就是 **JEI 自己建了两套倒排索引**：输入→配方、输出→配方。我们要做的查询能力和它同构，不需要发明新东西。

### 1.4 `/jei` 命令与 dump 能力（结论：没有）

- 唯一命令：`Common/src/main/java/mezz/jei/common/chat/JeiChatItemLinks.java:22` → `SHOW_RECIPE_COMMAND = "jei_internal_show"`；注册处 `Forge/src/main/java/mezz/jei/forge/chat/JeiInternalShowCommand.java:19-27`，只接收一个字符串 link 参数，用于聊天物品链接跳转配方。
- `grep -rin "dump" Common/src/main/java/mezz/jei` → **0 命中**。
- Debug 配置只有开关、没有导出（`Common/src/main/java/mezz/jei/common/config/DebugConfig.java`）：`debugIngredientsEnabled` / `debugGuis` / `debugInputs` / `debugInfoTooltipsEnabled` / `logSuffixTreeStats`，输出到 GUI tooltip 或日志，不是结构化配方 dump。
- 结论：**“运行时 dump 配方”必须自己写 mixin 或装第三方导出 mod**，JEI 本身不提供。这一点直接影响方案选型（见 §5）。

---

## 2. 两个整合包的真实 recipe type 统计

### 2.1 扫描方法（可复现）

脚本：`/tmp/scan_recipes.py`（已备份到 `.research/artifacts/scan_recipes.py`），逻辑：遍历 `mods/*.jar` → `zipfile.namelist()` 匹配 `^data/([^/]+)/recipes?/(.+)\.json$` → 解析 `type` → 落 JSONL。
复现命令：
~~~bash
python3 /home/guigui/mc/.research/artifacts/scan_recipes.py
# 产物: /tmp/recipe_scan/{Farming,zyjd}_recipes.jsonl  (逐条原文)
#       /tmp/recipe_scan/{Farming,zyjd}_types.json     (type -> 计数 + 来源 jar)
~~~

### 2.2 总量

| 指标 | Farming | zyjd |
|---|---|---|
| mod jar 数 | 278 | 228 |
| 配方 JSON 文件 | **29,296** | **6,648** |
| 不同 recipe type | **185** | **91** |
| 拆 `forge:conditional` / `meadow:conditional` 后的叶子配方 | 29,027 | 6,722 |
| 其中非配方数据表（见 2.4） | 597 | 51 |
| **可显示配方（估算）** | **28,430** | **6,671** |
| 解析失败（坏 JSON） | 1（`data/paintable/recipes/paintingBlocks.json`，内容不是 JSON） | 0 |
| 声明的 modId（mods.toml `[[mods]]` 段） | 273 | 224 |
| **死配方（type 所属 mod 未安装）** | **24**（IE 17 / jeed 5 / mekanism 2） | **96**（create 71 / IE 19 / jeed 6） |

> zyjd 的 71 条 `create:*` 是真死数据：`zyjd/mods/` 里没有任何 create jar，但这些 JSON 躺在 FarmersDelight、bygonenether、Delightful、cookingforblockheads 等 jar 的 `data/create/recipes/` 里。静态建库**必须**做 mod 存在性过滤，否则会告诉玩家“用机械搅拌器做”——那个服根本没有机械动力。

### 2.3 类型分布（前 20，含来源 mod）

**Farming（29,296 条 / 185 类）**

| # | recipe type | 文件数 | 主要来源 jar |
|---|---|---|---|
| 1 | `minecraft:stonecutting` | 9,439 | 方块小镇 yuushya 5,773 / Steam_Rails 930 / Quark 516 |
| 2 | `minecraft:crafting_shaped` | 7,794 | Quark 771 / cluttered 647 / Paintable 642 |
| 3 | `minecraft:crafting_shapeless` | 3,080 | Paintable 450 / refinedstorage 306 / create 274 |
| 4 | `forge:conditional` | 1,850 | CrockPot 495 / clayworks 431 / collectorsreap 362 |
| 5 | `create:mixing` | 1,167 | Steam_Rails 1,063 / create-meowchanics 28 / createaddition 21 |
| 6 | `bf_blockpack:crafting_shaped` | 1,082 | bf_blockpack（自带 JEI 分类 `WorkbenchJeiCategory`） |
| 7 | `create:sequenced_assembly` | 376 | Steam_Rails 350 / create-meowchanics 17 |
| 8 | `meadow:conditional` | 273 | letsdo-meadow |
| 9 | `create:item_application` | 262 | create-meowchanics 170 / create_connected 49 |
| 10 | `create:milling` | 249 | create 231 |
| 11 | `create:crushing` | 235 | create 201 / createdieselgenerators 22 |
| 12 | `kaleidoscope_cookery:pot` | 221 | kaleidoscopecookery 198 |
| 13 | `minecraft:smelting` | 177 | create 37 / Quark 13 |
| 14 | `create:filling` | 163 | BrewinAndChewin 53 / youkaisfeasts 39 |
| 15 | `farmersdelight:cutting` | 156 | FarmersDelight 106 / youkaisfeasts 24 |
| 16 | `create:mechanical_crafting` | 143 | Steam_Rails 128 |
| 17 | `create:deploying` | 120 | create 112 |
| 18 | `meadow:woodcutting` | 115 | letsdo-meadow |
| 19 | `kaleidoscope_cookery:stockpot` | 102 | kaleidoscopecookery 77 |
| 20 | `kaleidoscope_cookery:millstone` | 100 | kaleidoscopecookery 85 |

余下还有 `create:emptying` 97、`farmersdelight:cooking` 86、`automobility:auto_mechanic_table` 81、`crockpot:food_values` 80（假配方）、`plushie_buddies:workbench` 77、`create:splashing` 61、`crockpot:crock_pot_cooking` 60、`farm_and_charm:mincer` 56、`touhou_little_maid:altar_crafting` 44、`kaleidoscope_tavern:barrel` 42 …

**zyjd（6,648 条 / 91 类）**

| # | recipe type | 文件数 | 主要来源 jar |
|---|---|---|---|
| 1 | `minecraft:crafting_shaped` | 2,434 | Quark 771 / BiomesOPlenty 198 / atmospheric 191 |
| 2 | `forge:conditional` | 1,032 | Delightful 757 / atmospheric 236 |
| 3 | `minecraft:crafting_shapeless` | 980 | Quark 268 / FarmersDelight 85 |
| 4 | `minecraft:stonecutting` | 805 | Quark 516 / atmospheric 73 |
| 5 | `farmersdelight:cutting` | 345 | abnormals_delight 146 / FarmersDelight 126 |
| 6 | `minecraft:smelting` | 123 | Quark 13 |
| 7 | `farmersdelight:cooking` | 103 | FarmersDelight 27 / MyNethersDelight 20 |
| 8 | `aether:repairing` | 97 | aether |
| 9 | `minecraft:smithing_transform` | 86 | irons_spellbooks 38 |
| 10 | `fetzisdisplays:workbench` | 77 | fetzisdisplays |
| 11 | `minecraft:smoking` | 72 | — |
| 12 | `minecraft:campfire_cooking` | 68 | — |
| 13 | `aether:placement_conversion` | 38 | aether |
| 14 | `apotheosis:salvaging` | 27 | Apotheosis 15 / duelcraft 12 |
| 15 | `apotheosis:spawner_modifier` | 26 | Apotheosis |
| 16 | `quark:smithing_rune` | 18 | Quark |
| 17 | `create:filling` | 16 | irons_spellbooks 15（死配方） |
| 18 | `irons_spellbooks:alchemist_cauldron_*` | 16+16+15 | irons_spellbooks |
| 19 | `create:crushing` / `create:splashing` | 13 / 13 | bygonenether（死配方） |
| 20 | `apotheosis:fletching` | 13 | Apotheosis |

**覆盖率（决定“手工映射表要写多少条”）**

| 取前 N 类 | Farming 覆盖 | zyjd 覆盖 |
|---|---|---|
| top 10 | 87.3% | 91.5% |
| top 20 | 92.5% | 96.3% |
| top 30 | 95.1% | 98.1% |
| top 50 | 97.7% | 99.4% |

→ **给 top 30 类型配“机器/中文标签”就能覆盖 95%+ 的配方**，30 条人工映射的量级。

### 2.4 陷阱一：`data/<ns>/recipes/` 里混着**不是配方**的数据

静态扫描的头号翻车点。实测存在的非配方类型：

| type | 条数(Farming) | 实际是什么（原文证据） |
|---|---|---|
| `crockpot:food_values` | 80（+448 条藏在 conditional 里） | 食物营养值表：`{"type":"crockpot:food_values","items":["minecraft:apple"],"values":{"FRUIT":1}}` |
| `aether:item_placement_ban` / `block_placement_ban` | 4 / 3 | 维度放置黑名单：`{"biome":"#aether:ultracold","bypass":{...},"ingredient":{...}}` |
| `quark:mixed_exclusion` | 6 | 木种互斥开关：`{"subtype":"chest4","conditions":[...]}` |
| `apotheosis:keep_nbt_enchanting` / `spawner_modifier` | 1 / 26 | 附魔 NBT 白名单 / 刷怪笼修改规则 |
| `jeed:effect_provider` | 9 | JEI“信息页”伪配方（不是合成） |
| `farmersdelight:food_serving` | 3 | 食物摆放规则 |
| `createaddition:liquid_burning` | 14 | 液体燃料表（只有 `burnTime`，没有输出） |

Farming 一共 **597** 条这类东西（占叶子配方 2.1%）。不过滤的后果：AI 会告诉你“苹果可以通过 FRUIT 配方获得”。

### 2.5 陷阱二：`forge:conditional` 是包装器，不是配方

Farming 1,850 条 / zyjd 1,032 条，结构（真实样本，一条被 `forge:false` 关掉的配方）：
~~~json
{"type":"forge:conditional","recipes":[
  {"conditions":[{"type":"forge:false"}],
   "recipe":{"type":"minecraft:crafting_shapeless","ingredients":[{"item":"this_item:does_not_exist"}],"result":{"item":"this_item:does_not_exist"}}}]}
~~~

包装里的真实配方数量不小，Farming 前几名：`crockpot:food_values` 448、`minecraft:crafting_shaped` 409、`minecraft:stonecutting` 250、`woodworks:sawmill` 237、`minecraft:crafting_shapeless` 207、`farmersdelight:cooking` 73。
条件类型 top：`forge:mod_loaded` 609、`clayworks:config` 430、`woodworks:config` 284、`forge:and` 226、`collectorsreap:enabled` 200、`create_connected:feature_enabled` 120、`sullysmod:mod_features` 89。

**能不能静态求值这些条件？** 部分能（`forge:mod_loaded` 用 modId 表判断、`forge:false` 直接丢），但 `*:config`（读 mod 的 config 文件）、`forge:tag_empty`（要展开 tag）做不到。务实做法：**能判的判掉，判不了的保留并标记 `conditional:unknown`**，让 AI 措辞降级（“可能”）。

### 2.6 陷阱三：KubeJS 会动态增删配方（只能运行时拿）

Farming 的 KubeJS 规模（实测）：
- `kubejs/server_scripts/` **135** 个文件，其中 `server_scripts/recipes/` **47** 个
- 全量 grep：`event.add` **194** 次、`event.remove` **121** 次
- `kubejs/data/**/recipes/*.json` **242** 个（KubeJS 生成为 datapack 的静态配方，这个能扫到）

zyjd 只有 1 个 server script（`duelcraft_broken_seal_ritual.js`），改动面小得多。

→ 静态扫描 **漏掉 194 条新增 + 121 条删除**（Farming）。删除尤其致命：AI 会教玩家做一个已经被整合包删掉的配方。

### 2.7 陷阱四：`result` 键名有 4 种，还有 8 类“输出不在 JSON 里”

实测键名分布（顶层）：

| 键 | Farming | zyjd |
|---|---|---|
| `result` | 23,824 | 5,290 |
| `results` | 2,940 | 93 |
| `output` | 111 | 0 |
| `outputs` | 0 | 27 |

以及“根本没有 output 键”的类型（实测原文）：

| type | 原文 | 输出在哪 |
|---|---|---|
| `meadow:woodcutting`(115) | `{"type":"meadow:woodcutting","inputItem":{"tag":"minecraft:acacia_logs"},"outputItem":"minecraft:acacia_button","outputAmount":5}` | `outputItem` / `outputAmount`（连输入都叫 `inputItem`） |
| `aether:repairing`(97) | `{"type":"aether:repairing","ingredient":{"item":"minecraft:bow"},"repairTime":600}` | **输出 = 输入本身**（修耐久） |
| `minecraft:smithing_trim`(6) | `{"type":"minecraft:smithing_trim","template":{...},"base":{...},"addition":{"tag":"minecraft:trim_materials"}}` | **无 result**，输出 = base 加纹饰 |
| `apotheosis:reforging`(5) | 同上套路 | 输出在代码里算 |
| `kaleidoscope_tavern:pressing_tub`(6) | `{"fluid":"kaleidoscope_tavern:glow_berries_juice","fluid_amount":125,"ingredient":{"item":"minecraft:glow_berries"}}` | 输出是**流体**，键名 `fluid` + `fluid_amount` |
| `youkaisfeasts:immediate_soup`(4) | `{"id":"youkaisfeasts:cream","input":[{"item":"youkaisfeasts:bowl_of_cream"}],"time":0}` | 输出键叫 `id` |
| `createaddition:liquid_burning`(14) | `{"input":{"fluid":"tconstruct:blazing_blood","amount":1000},"burnTime":6400}` | 没有输出，是燃料表 |
| `apotheosis:salvaging`(27, zyjd) | `{"input":{...},"outputs":[{"min_count":1,"max_count":3,"stack":{"item":"cataclysm:black_steel_ingot"}}]}` | 输出**套在 `stack` 里** + min/max 数量 |

---

## 3. 通用配方 schema

### 3.1 设计原则（都是从实测倒推的）

1. **输入输出统一成“槽位表”**，不要塞 JSON 数组：一条配方 N 行输入、M 行输出，才能建倒排索引。
2. **ingredient 三态**：`item` / `tag` / `fluid`。tag 不展开（展开时机见 §6.2），但必须能展开。
3. **数量用 min/max + chance**：`{"count":2}`、`{"min_count":1,"max_count":3}`、`{"chance":0.75}` 都要装得下。
4. **`recipe_type` 就是机器/category 的 key**，另用一张小表映射到“机器方块 + 中文名”。
5. **保留原始 JSON**（`raw_json`），adapter 解析不了的字段回退给 LLM 看原文。

### 3.2 JSON 视图（一条配方的规范形态）

~~~jsonc
{
  "pack": "Farming",
  "recipe_id": "create:crushing/aluminum_ore",      // datapack id（去重/覆盖的键）
  "recipe_type": "create:crushing",
  "source_jar": "[机械动力] create-1.20.1-6.0.8.jar",
  "category": { "machine": "create:crushing_wheel", "label_zh": "粉碎轮" },
  "time_ticks": 400,
  "xp": null,
  "energy": null,
  "conditional": { "status": "passed" },            // passed|failed|unknown
  "inputs": [
    { "slot": 0, "role": "input", "kind": "tag",  "ref": "forge:ores/aluminum", "count": 1 }
  ],
  "outputs": [
    { "slot": 0, "kind": "item", "ref": "create:crushed_raw_aluminum", "count_min": 1, "count_max": 1, "chance": 1.0 },
    { "slot": 1, "kind": "item", "ref": "create:crushed_raw_aluminum", "count_min": 1, "count_max": 1, "chance": 0.75 },
    { "slot": 2, "kind": "item", "ref": "create:experience_nugget",    "count_min": 1, "count_max": 1, "chance": 0.75 }
  ],
  "raw_json": { "...": "原始 JSON，调试与兜底" }
}
~~~

### 3.3 SQLite DDL（已实测建库并灌入 34,284 条配方）

~~~sql
PRAGMA journal_mode=WAL;

CREATE TABLE recipe (
  id          INTEGER PRIMARY KEY,
  pack        TEXT NOT NULL,              -- 'Farming' | 'zyjd'
  recipe_id   TEXT NOT NULL,              -- 'create:crushing/aluminum_ore'
  recipe_type TEXT NOT NULL,              -- 'create:crushing'
  source_jar  TEXT,
  time_ticks  INTEGER,                    -- processingTime/cookingtime/time/...
  xp          REAL,
  energy      REAL,
  conditional TEXT DEFAULT 'passed',      -- passed|failed|unknown
  raw_json    TEXT,                       -- 兜底：解析不了的字段给 LLM 看原文
  UNIQUE(pack, recipe_id)                 -- 同 id 多 jar 出现时后者覆盖（datapack 语义）
);
CREATE TABLE recipe_input (
  recipe_pk INTEGER NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
  slot      INTEGER NOT NULL,
  role      TEXT NOT NULL,                -- input | tool | container | catalyst
  kind      TEXT NOT NULL,                -- item | tag | fluid
  ref       TEXT NOT NULL,                -- minecraft:iron_ingot / forge:ingots/iron / minecraft:water
  count     INTEGER DEFAULT 1,
  PRIMARY KEY (recipe_pk, slot, role, kind, ref)
);
CREATE TABLE recipe_output (
  recipe_pk INTEGER NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
  slot      INTEGER NOT NULL,
  kind      TEXT NOT NULL,                -- item | fluid
  ref       TEXT NOT NULL,
  count_min INTEGER DEFAULT 1,
  count_max INTEGER DEFAULT 1,
  chance    REAL    DEFAULT 1.0,
  PRIMARY KEY (recipe_pk, slot)
);

-- 物品/名字/别名
CREATE TABLE item_name  ( id TEXT PRIMARY KEY, kind TEXT, name_zh TEXT, name_en TEXT );
CREATE TABLE item_alias ( alias TEXT, item_id TEXT, PRIMARY KEY(alias, item_id) );
CREATE TABLE item_tag   ( tag TEXT, item_id TEXT, PRIMARY KEY(tag, item_id) );   -- tag 展开缓存

-- 机器/分类（1 type : N machine）
CREATE TABLE recipe_category (
  type      TEXT NOT NULL,
  machine   TEXT NOT NULL,                -- 'create:crushing_wheel'
  label_zh  TEXT,                         -- '粉碎轮'
  source    TEXT,                         -- 'manual' | 'catalyst_dump' | 'heuristic'
  PRIMARY KEY (type, machine)
);

CREATE INDEX ix_in_ref  ON recipe_input(ref);
CREATE INDEX ix_in_tag  ON recipe_input(kind, ref);
CREATE INDEX ix_out_ref ON recipe_output(ref);
CREATE INDEX ix_rec_type ON recipe(recipe_type);
~~~
（实测：`/tmp/recipe.db` 共 34,284 recipe / 94,809 input / 35,657 output 行，WAL 模式。）

### 3.4 10 个真实配方的映射演示（原文 + 装进去之后的样子）

> 原文取自 `/tmp/recipe_scan/{Farming,zyjd}_recipes.jsonl`，完整版见 `.research/artifacts/examples.md`。

**(1) `minecraft:crafting_shaped` — 有序合成（Farming 7,794 / zyjd 2,434）**
~~~json
{"type":"minecraft:crafting_shaped","category":"building","pattern":["XYX","YXY","XYX"],
 "key":{"X":{"item":"minecraft:iron_ingot"},"Y":{"item":"minecraft:iron_block"}},
 "result":{"item":"bf_blockpack:air_conditioner","count":1},"group":"special"}
~~~
映射：`inputs` ← 展开 pattern 的 9 个格子（X→iron_ingot×5、Y→iron_block×4，`slot` 记 0..8），`outputs` ← `[{item:bf_blockpack:air_conditioner, 1}]`。**注意**：输入数 = 图案里非空格子数，重复物品要么按槽位保留、要么合并计数，否则“要 5 个铁锭”会被说成“要 1 个”。

**(2) `minecraft:smelting` — 烧炼（`result` 是字符串，不是对象）**
~~~json
{"type":"minecraft:smelting","category":"food","cookingtime":200,"experience":0.35,
 "ingredient":{"item":"collectorsreap:platinum_bass"},"result":"collectorsreap:cooked_platinum_bass"}
~~~
映射：`inputs=[{item, platinum_bass, 1}]`、`outputs=[{item, cooked_platinum_bass, 1, chance 1.0}]`、`time_ticks=200`、`xp=0.35`。**证据**：`result` 在这里是字符串、在 (1) 里是对象 → 归一化必须两种都吃。

**(3) `create:crushing` — 粉碎（多产出 + 概率 + 条件）**
~~~json
{"type":"create:crushing",
 "conditions":[{"type":"forge:not","value":{"type":"forge:tag_empty","tag":"forge:ores/aluminum"}}],
 "ingredients":[{"tag":"forge:ores/aluminum"}],"processingTime":400,
 "results":[{"item":"create:crushed_raw_aluminum"},
            {"chance":0.75,"item":"create:crushed_raw_aluminum"},
            {"chance":0.75,"item":"create:experience_nugget"}]}
~~~
映射：`inputs=[{tag, forge:ores/aluminum, 1}]`；`outputs` 3 行，第 1 行 chance=1.0、后两行 0.75；`time_ticks=400`。**这条同时是“tag 输入”和“概率产出”的样板**（全库 884 个 `chance<1` 的输出行）。

**(4) `create:mixing` — 搅拌（`ingredients` 是数组，无 `count` 键）**
~~~json
{"conditions":[{"type":"forge:mod_loaded","modid":"create"}],"type":"create:mixing",
 "ingredients":[{"item":"farmersdelight:cabbage"}],
 "results":[{"item":"farmersdelight:cabbage_leaf","count":2}]}
~~~
映射：`inputs=[{item, farmersdelight:cabbage, 1}]`、`outputs=[{item, cabbage_leaf, count_min=2, count_max=2}]`。**没有 `processingTime`** → JEI 里显示的是代码默认值，静态拿不到 → `time_ticks=NULL` 是正常情况（全库只有 2,248/34,284 条有 time）。

**(5) `create:sequenced_assembly` — 序列组装（嵌套子配方，最难建模）**
~~~json
{"type":"create:sequenced_assembly","ingredient":{"item":"minecraft:ender_eye"},"loops":4,
 "results":[{"item":"cataclysm:mech_eye"}],
 "sequence":[
   {"type":"create:filling","ingredients":[{"item":"minecraft:ender_eye"},{"amount":500,"fluid":"minecraft:lava","nbt":{}}],"results":[{"item":"minecraft:ender_eye"}]},
   {"type":"create:deploying","ingredients":[{"item":"minecraft:ender_eye"},{"item":"minecraft:redstone_block"}],"results":[{"item":"minecraft:ender_eye"}]},
   {"type":"create:deploying","ingredients":[{"item":"minecraft:ender_eye"},{"item":"create:industrial_iron_block"}],"results":[{"item":"minecraft:ender_eye"}]},
   {"type":"create:pressing","ingredients":[{"item":"minecraft:ender_eye"}],"results":[{"item":"minecraft:ender_eye"}]},
   {"type":"create:deploying","ingredients":[{"item":"minecraft:ender_eye"},{"item":"create:precision_mechanism"}],"results":[{"item":"minecraft:ender_eye"}]}]}
~~~
映射：`inputs` = 起手物 `ender_eye` + 把 sequence 里除“半成品”之外的原料全并进来（redstone_block、industrial_iron_block、precision_mechanism、500mB lava）→ 一条 5 输入 + `loops=4`。`raw_json` 保留 sequence 让 LLM 能复述步骤。这是唯一值得写专用 adapter 的常见类型（Farming 376 条，占 1.3%）。

**(6) `farmersdelight:cooking` — 厨锅（时间 + 经验）**
~~~json
{"type":"farmersdelight:cooking","cookingtime":200,"experience":1.0,
 "ingredients":[{"item":"minecraft:apple"},{"item":"minecraft:apple"},{"item":"minecraft:sugar"}],
 "recipe_book_tab":"drinks","result":{"item":"farmersdelight:apple_cider"}}
~~~
映射：3 个输入槽（apple 出现两次：建议**保留两个槽**，展示时再合并——玩家看到的就是锅里 2 格苹果）；`time_ticks=200`、`xp=1.0`。

**(7) `farmersdelight:cutting` — 砧板（带工具要求 + 多产出 + 声音）**
~~~json
{"type":"farmersdelight:cutting","ingredients":[{"item":"minecraft:acacia_log"}],
 "result":[{"item":"minecraft:stripped_acacia_log"},{"item":"farmersdelight:tree_bark"}],
 "sound":"minecraft:item.axe.strip",
 "tool":[{"type":"farmersdelight:tool_action","action":"axe_strip"},{"tag":"minecraft:axes"}]}
~~~
映射：`inputs` 除了原木，**还要建 `role='tool'` 的行**：`{tag, minecraft:axes}`（第一项是 `tool_action` 伪 ingredient，解析不出 ref → 记 raw_json 并展示“需要斧”）。`outputs` 2 行。这条证明 `role` 字段是必要的。

**(8) `apotheosis:salvaging` — 拆解（输出套 `stack` + min/max 数量）**
~~~json
{"type":"apotheosis:salvaging","conditions":[{"type":"apotheosis:module","module":"adventure"}],
 "input":{"item":"cataclysm:black_steel_axe"},
 "outputs":[{"min_count":1,"max_count":3,"stack":{"item":"cataclysm:black_steel_ingot"}}]}
~~~
映射：`inputs=[{item, black_steel_axe,1}]`、`outputs=[{item, black_steel_ingot, count_min=1, count_max=3, chance=1.0}]`。
**实测教训**：通用抽取器第一次跑把这个类型**整个丢掉**（对 `{"min_count":1,...,"stack":{...}}` 返回空），加一条“dict 里有 `stack` 就下钻”的规则后，30 个 output 全部救回（实测 fixed=30, bad=0）。

**(9) `touhou_little_maid:altar_crafting` — 输出 id 藏在 NBT 里**
~~~json
{"type":"touhou_little_maid:altar_crafting",
 "output":{"type":"minecraft:item","nbt":{"Item":{"id":"netmusic:music_player_backpack","Count":1}}},
 "power":0.2,"ingredients":[{"item":"touhou_little_maid:maid_backpack_middle"},{"item":"netmusic:music_player"}]}
~~~
映射：output 没有 `item` 键，id 埋在 `nbt.Item.id` → 正则兜底（实测可行）。

**(10) `kaleidoscope_cookery:pot` — 6 个同 tag 输入 + 容器 + 翻炒次数**
~~~json
{"type":"kaleidoscope_cookery:pot","carrier":{"item":"minecraft:bowl"},
 "ingredients":[{"tag":"maid_restaurant:braised_fish_ingredient"},{"tag":"maid_restaurant:braised_fish_ingredient"},{"tag":"maid_restaurant:braised_fish_ingredient"},{"tag":"maid_restaurant:braised_fish_ingredient"},{"tag":"maid_restaurant:braised_fish_ingredient"},{"tag":"maid_restaurant:braised_fish_ingredient"}],
 "result":{"item":"kaleidoscope_cookery:braised_fish"},"stir_fry_count":3,"time":200}
~~~
映射：`carrier` → `role='container'` 一行（碗）；6 个 tag 槽 → 可合并成 `{tag, ..., count=6}`；`time=200`。

### 3.5 装载实测：通用抽取器能装下多少

用上面 schema 写了通用抽取器（`/tmp/an7.py`，已备份为 `.research/artifacts/load_sqlite.py`），对两个包全量灌库：

| 包 | 叶子配方 | 成功入库 | 丢弃：数据表 | 丢弃：无 output 键 | 覆盖类型 |
|---|---|---|---|---|---|
| Farming | 29,027 | **28,042** | 597 | 357 | 128 / 185 |
| zyjd | 6,722 | **6,242** | 49 | 288 | 60 / 106 |

- 按**配方条数**：Farming 99.2%、zyjd 95.9% 能自动装进 schema。
- 按**类型数**：只有 69% / 57%，因为稀有类型常常“整个类型都没有标准 output 键”（`aether:repairing` 103、`aether:placement_conversion` 38、`apotheosis:salvaging` 27、`quark:smithing_rune` 18、`kaleidoscope_grilling:*` …）。
- 这些掉队类型的配方量占比：**Farming 0.76% / zyjd 4.14%** → **不值得为它们写 46 个 adapter**，进 `raw_json` 兜底即可。
- 建议只手工写 5 个 adapter：`create:sequenced_assembly`、`meadow:woodcutting`、`apotheosis:salvaging`（`stack`）、`kaleidoscope_tavern:pressing_tub`（流体输出）、`touhou_little_maid:altar_crafting`（NBT）。

---

## 4. 查询能力设计

### 4.1 三种问法 → 三条 SQL

**(a)「X 怎么做」→ 按 output 反查**
~~~sql
SELECT r.recipe_type, r.recipe_id, r.time_ticks, r.xp, r.source_jar,
       i.role, i.kind, i.ref, i.count
FROM recipe_output o
JOIN recipe r            ON r.id = o.recipe_pk
LEFT JOIN recipe_input i ON i.recipe_pk = r.id
WHERE o.ref = :item_id AND r.pack = :pack
ORDER BY (o.chance < 1.0), r.recipe_type, i.slot;
~~~
实测（中文「苹果酒 怎么做」，中文→id 得 `farmersdelight:apple_cider`）：
~~~
farmersdelight:cooking      | farmersdelight/cooking/apple_cider | time=200 | apple, apple, sugar
create:filling              | ...                                | -        | glass_bottle + 500mB apple_cider(fluid)
brewinandchewin:keg_pouring | ...                                | -        | (流体注入)
~~~
→ 一个物品有 3 条不同机器的做法，**正好是玩家问“怎么做”想要的完整答案**。

**(b)「X 能干嘛 / 有什么用」→ 按 input 反查**
~~~sql
SELECT DISTINCT r.recipe_id, r.recipe_type, o.ref, o.count_min, o.count_max, o.chance
FROM recipe_input i
JOIN recipe r        ON r.id = i.recipe_pk
JOIN recipe_output o ON o.recipe_pk = r.id
WHERE i.ref = :item_id AND i.kind IN ('item','tag')
LIMIT :n;
~~~
⚠️ **必须 `DISTINCT` / `GROUP BY`**：`recipe_input` 一行一槽，join 输出会按槽数翻倍。实测未去重时 `farm_and_charm:chicken_coop` 出现 3 次（用了 3 个铁锭）。

**(c)「有哪台机器能做 X」→ 查 `recipe_category`**
~~~sql
SELECT DISTINCT c.machine, c.label_zh, r.recipe_type
FROM recipe_output o
JOIN recipe r           ON r.id = o.recipe_pk
JOIN recipe_category c  ON c.type = r.recipe_type
WHERE o.ref = :item_id;
~~~

### 4.2 中文 → item id：子串 + 别名，够用

**实测数据**（从各 jar `assets/<ns>/lang/zh_cn.json` 的 `item.*` / `block.*` 键导出）：

| 指标 | Farming | zyjd |
|---|---|---|
| 有名字的物品/方块 id（zh 文件） | 19,016 | 6,304 |
| 其中同时有 en_us | 18,748 | 6,174 |
| 中文名含 CJK 字符 | 18,248（97.3%） | 6,072（98.3%） |
| 可直接用于匹配（过滤 tooltip 等伪键后） | **15,512** | — |
| 不同中文名 | 14,188 | 5,941 |
| 一个中文名对应 >1 个 id | 997 | 143 |

**实测查询行为**：
~~~
query '苹果酒': 3 hits [('farmersdelight:apple_cider','苹果酒'), ('displaydelight:apple_cider','苹果酒'), ('bountifulfares:apple_cider_jar','苹果酒罐')]
query '搅拌器': 3 hits [('create:mechanical_mixer','动力搅拌器'), ('create:whisk','搅拌器'), ('laowu:cat_mixer','猫搅拌器')]
query '卷心菜': 11 hits [('farmersdelight:cabbages','卷心菜'), ('farmersdelight:cabbage','卷心菜'), ('farmersdelight:cabbage_crate','箱装卷心菜'), ...]
query '坩埚'  : 0 hits
query '工业铁块': 2 hits [('create:industrial_iron_block','工业铁块'), ('create:weathered_iron_block','锈蚀的工业铁块')]
~~~
**务实建议（按性价比排序）**：
1. **精确名优先，再子串，长的优先**：`苹果酒` 精确命中 2 个 id，`苹果酒罐` 是子串——排序键 `(name != query, len(name), kind)`。实测这条规则直接把正确物品排第一。
2. **`kind` 消歧**：`farmersdelight:cabbages`（方块）vs `farmersdelight:cabbage`（物品）；997 个同名多 id 的案例基本靠 item/block 优先级 + 是否出现在配方里解决。
3. **别名表**：只补“玩家口语 ≠ 官方译名”的（“工作台”→`crafting_table`、“锅”→`cooking_pot` / `stockpot`、“机械手”→`create:deployer`）。几十到几百条人工活，比任何模型都划算。
4. **别上拼音、别上向量**：中文译名本身高度规范，子串命中率实测已足够；拼音只对“输入法没切/打错字”有效，而这个插件入口是聊天文本。向量检索会引入“相似但错”的召回（把“苹果酒”召回“苹果汁”），对配方查询是负收益。
5. **必须处理“名字缺失”**：`坩埚` 0 命中说明该物品没中文名或译名不同（如 `irons_spellbooks:alchemist_cauldron`）。返回“没找到，你要找的是不是…（列 3 个最相近的）”比静默失败好。

### 4.3 机器映射表怎么建（唯一静态拿不到的东西）

**结论：catalyst（“哪台机器能做这个”）只存在于 mod 的 Java 代码里**，`addRecipeCatalysts()` 没有任何 JSON 落盘。静态路线只有三个来源：

1. **命名约定 + 人工表（主力，够覆盖 95%）**。实测已确认这些方块 id 真实存在于包里（方法：列出 jar 的 `assets/<ns>/blockstates/*.json` 名字再对齐 type）：

| recipe_type | 机器（实测存在的 block id） | 备注 |
|---|---|---|
| `create:mixing` | `create:mechanical_mixer`（中文“动力搅拌器”） | 词面不匹配，必须人工 |
| `create:crushing` | `create:crushing_wheel` + `create:millstone` | 1 类多机器 |
| `create:milling` | `create:millstone` | |
| `create:pressing` | `create:mechanical_press`（+ `create:basin`） | |
| `create:sequenced_assembly` | `create:mechanical_press` / `deployer` / `spout` / `encased_fan` / `mechanical_saw` | 多机器 |
| `farmersdelight:cooking` | `farmersdelight:cooking_pot` | |
| `farmersdelight:cutting` | `farmersdelight:cutting_board` | |
| `kaleidoscope_cookery:pot` | `kaleidoscope_cookery:stockpot` / `pot` | |
| `kaleidoscope_cookery:chopping_board` | `kaleidoscope_cookery:chopping_board` | 同名 |
| `farm_and_charm:stove` | `farm_and_charm:stove` | 同名 |
| `farm_and_charm:mincer` | `farm_and_charm:mincer` | 同名 |
| `vinery:wine_fermentation` | `vinery:fermentation_barrel` | |
| `brewinandchewin:keg_pouring` | `brewinandchewin:keg` | |
| `apotheosis:salvaging` | `apotheosis:salvaging_table` | zyjd 实测存在 |

2. **运行时 dump 的 catalyst（最准）**：同事那条线若能 dump `createRecipeCatalystLookup(type)`，直接得权威映射，写 `recipe_category.source='catalyst_dump'`。**这是运行时路线不可替代的价值。**
3. **多机器必须支持**：一个 type 常对应多台机器，所以 `recipe_category` 用 `(type, machine)` 复合主键（上面 DDL 已按这个建）。

---

## 5. 静态 JSON 扫描 vs 运行时 dump

| 维度 | 静态扫描（扫 jar 里的 `data/**/recipes`） | 运行时 dump（起服务端 + mixin/插件导出） |
|---|---|---|
| 配方本体 | ✅ 全部 JSON 原文（29,296 / 6,648） | ✅ `RecipeManager.getRecipes()` 反序列化后的对象 |
| KubeJS `event.add` | ❌ 194 条拿不到 | ✅ 已在表里 |
| KubeJS `event.remove` | ❌ 121 条删除看不到（**会教玩家做已删配方**） | ✅ 已消失 |
| `forge:conditional` 求值 | ⚠️ 只能判 `mod_loaded` / `false`，`*:config` / `tag_empty` 判不了 | ✅ 服务端已按真实配置过滤 |
| tag → 实际物品 | ⚠️ 需自己扫 `data/**/tags/items`（Farming 2,922 个、zyjd 1,636 个 item tag 文件）并实现继承+递归 | ✅ 直接拿到展开结果 |
| **catalyst（机器）** | ❌ 在代码里，静态拿不到 | ✅ `RecipeCatalystBuilder` 里有权威映射 |
| category 显示名/图标 | ❌ | ✅ |
| 概率/时间/经验 | ✅ JSON 里有（`chance` 459 条、`time` 2,248 条） | ✅ |
| 依赖环境 | 无（纯 zipfile + json，秒级） | 要起服（1.20.1 Forge 278 mod，首启几分钟）、要写 mixin/mod |
| 可重复性 | 100%（产物可进 git） | 受 mod 版本/config/世界状态影响 |
| recipe id | ✅ 就是文件路径（datapack 语义） | ✅ 带 namespace |

**两者结合的正确分工**：
- **静态 = 知识库底座（离线、可增量、能进 git）**：物品名、配方本体、时间/概率、tag 表、机器人工映射。
- **运行时 = 校准层（低频一次性生成，作为静态库的 override）**：① 服务端实际存在的 recipe id 集合（删掉被 KubeJS/条件删掉的）；② `type → catalyst item` 表（补机器）；③ tag 展开快照。
- **合并策略**：运行时优先（`source='runtime'`），静态兜底；冲突记 diff（整合包更新后能立刻发现“配方被删了 121 条”）。
- **不建议**只静态（会教玩家做不存在的配方、说错机器）；也不建议只运行时（快照会过期、每次都要起服、运维成本高）。

---

## 6. 现实风险（都有实测数字）

### 6.1 KubeJS 动态改配方 —— 最大风险，且不可静态解
Farming：`event.add` 194 / `event.remove` 121，分散在 47 个 `server_scripts/recipes/*.js`。删除的具体文件（grep 命中）：
- `kubejs/server_scripts/recipes/vinery/remove_grapes.js`（14 处 remove）
- `kubejs/server_scripts/recipes/crafting/zax/remove.js`（11 处）
- `kubejs/server_scripts/zzz_cleanup/kaleidoscope_cookery_tea.js`（9 处）

影响：静态库会多出最多 121 条“幽灵配方”。**缓解**：静态标 `source='json'`、运行时标 `source='runtime'`，回答优先 runtime；没有 runtime 快照时对 Farming 的回答加一句“以游戏内 JEI 为准”。zyjd 只有 1 个 server script → 这个服静态基本够用。

### 6.2 tag 展开 —— 不展开就等于没回答
Farming 输入槽里 **10,178 个是 tag**（占 58,221 个 item 引用的 17.5%），zyjd 3,334 / 15,571（21.4%）。`create:crushing` 的输入是 `forge:ores/aluminum`——玩家问“铝矿石怎么粉碎”，不展开就匹配不上具体物品。
**缓解**：扫 `data/**/tags/items/**.json` 建 `item_tag` 表（Farming 2,922 个、zyjd 1,636 个），支持 `#tag` 递归展开（防环）。纯静态可解，**建议第一版就做**，否则“能做什么/怎么做”会大面积漏召回。

### 6.3 概率产出 —— 别把 0.75 说成“一定给”
Farming 459 条配方含 `chance`，884 个输出行 `chance<1`。典型 `create:crushing` 给 0.75 概率的副产物。
**缓解**：`recipe_output.chance` 进 schema（已进），回答模板写“75% 概率额外产出 X”。

### 6.4 上下文爆炸 —— 实测会炸
单个物品的配方数实测：
- 「能干嘛」最多：`minecraft:stick` **1,345** 条、`ordertocook:chair` 451、`minecraft:sugar` 422、`minecraft:iron_ingot` **406**、`minecraft:chest` 239
- 「怎么做」最多：`laowu:cat_pancake` 171、`create:experience_nugget` 151、`minecraft:glass_bottle` 103
- 单配方输出数最多 15，输入槽最多 13

直接把 1,345 条塞进 LLM 会立刻爆。**缓解（必须做）**：
1. 硬上限 `LIMIT 8~10`，排序：同类机器优先 → 时间短优先 → 有中文名优先；
2. 分组聚合：先告诉 LLM “共 406 条，涉及 12 类机器（每类 2 条示例）”，让它决定要不要下钻；
3. 只回传压缩形态（`type + 机器中文名 + 3 个关键输入 + 输出`），原文按需二次查询。

### 6.5 死配方（mod 未安装）
zyjd **96 条**（`create:*` 71 + `immersiveengineering:*` 19 + `jeed:*` 6），Farming 24 条（IE 17 + jeed 5 + mekanism 2）。
不处理就会告诉玩家“用机械搅拌器”，而 zyjd 根本没有机械动力。**缓解**：入库前用 `mods.toml` 的 `[[mods]]` 段 modId 集合过滤——注意**不能用依赖段里的 modId**：我第一次用全文正则把 `create` 判成已安装（因为它出现在 `[[dependencies]]` 里），改成只解析 `[[mods]]` 后才发现这 71 条。

### 6.6 数据表混进配方目录
Farming 597 条（`crockpot:food_values` 448+80、`aether:*_placement_ban`、`quark:mixed_exclusion` …）。**缓解**：黑名单 + “没有 inputs 或没有 outputs 的类型标 `is_recipe=false`”。

### 6.7 输出不在 JSON 里的类型
`aether:repairing` 103、`aether:placement_conversion` 38、`apotheosis:salvaging` 27、`minecraft:smithing_trim` 6、`kaleidoscope_tavern:pressing_tub` 6（流体输出）。
**缓解**：不追着写 adapter（占 0.76%/4.14%），回退 `raw_json` 让 LLM 读原文；但**必须区分“查不到”和“我们没解析”**，别把它们报成“没有配方”。

### 6.8 物品名缺失 / 一名多物
997 个中文名对应多个 id，`坩埚` 0 命中。**缓解**：见 §4.2 的排序 + 别名表 + “找不到就反问”。

---

## 附录 A：产物与复现

| 路径 | 内容 |
|---|---|
| `.research/artifacts/scan_recipes.py` | 扫描器（遍历 jar → recipe JSONL + type 统计 + lang 索引） |
| `.research/artifacts/load_sqlite.py` | schema + 通用抽取器 + 灌库（实测 34,284 条） |
| `.research/artifacts/Farming_types.json` / `zyjd_types.json` | 每 type 计数 + 每个 type 的 top 来源 jar |
| `.research/artifacts/Farming_names.json` / `zyjd_names.json` | item id → 中英文名 + kind |
| `.research/artifacts/examples.md` | 12 个真实配方原文（本文引用的全部样本） |
| `/tmp/recipe.db` | 34,284 配方 / 94,809 输入槽 / 35,657 输出槽的 SQLite（可重建） |

复现：
~~~bash
python3 /home/guigui/mc/.research/artifacts/scan_recipes.py     # 约 40s，产出 /tmp/recipe_scan/*.jsonl
python3 /home/guigui/mc/.research/artifacts/load_sqlite.py      # 建 /tmp/recipe.db
sqlite3 /tmp/recipe.db "SELECT recipe_type,COUNT(*) FROM recipe GROUP BY 1 ORDER BY 2 DESC LIMIT 5"
~~~

## 附录 B：关键源码位置（clone 自 `mezz/JustEnoughItems` 分支 `1.20.1`）

| 结论 | 文件:行 |
|---|---|
| 配方来自客户端 `RecipeManager`（服务端下发） | `Forge/src/main/java/mezz/jei/forge/JustEnoughItemsClient.java:109-112` |
| 下发包是 `ClientboundUpdateRecipesPacket` | `Fabric/src/main/java/mezz/jei/fabric/mixin/ClientPacketListenerRecipeUpdateMixin.java:22-31` |
| 服务端不发配方时的兜底 + “不含服务端 mod 配方” | `Common/src/main/java/mezz/jei/common/recipes/VanillaClientRecipeLoader.java:23-29` |
| mod 必须主动注册 | `CommonApi/src/main/java/mezz/jei/api/registration/IRecipeRegistration.java:44-49` |
| catalyst = 机器声明 | `CommonApi/src/main/java/mezz/jei/api/registration/IRecipeCatalystRegistration.java:33-57` |
| 双向索引 INPUT/OUTPUT | `Library/src/main/java/mezz/jei/library/recipes/RecipeManagerInternal.java:53` |
| 运行时查询 API | `CommonApi/src/main/java/mezz/jei/api/recipe/IRecipeManager.java:29-66` |
| `/jei` 只是聊天链接命令 | `Common/src/main/java/mezz/jei/common/chat/JeiChatItemLinks.java:22`、`Forge/src/main/java/mezz/jei/forge/chat/JeiInternalShowCommand.java:19-27` |
| 无 dump 能力 | 在 Common/src/main/java/mezz/jei 下 grep “dump” → 0 命中；`Common/src/main/java/mezz/jei/common/config/DebugConfig.java` 只有开关 |
| 1.20.1 无 `IRecipeWrapper` | 对 jei-1.20.1-forge-15.49.0.191.jar 执行 `unzip -l` 后 grep RecipeWrapper → 0 命中 |

文档 URL：
- https://github.com/mezz/JustEnoughItems
- https://github.com/mezz/JustEnoughItems/wiki/Recipes-Overview-%5BMinecraft-1.16.5-to-1.18.2%5D （覆盖 1.16.5–1.20.1；**不要**看无版本号那页，那是 1.12.2 的 `IModRegistry` 老 API）
- https://github.com/mezz/JustEnoughItems/wiki/Recipe-Categories-%5BMinecraft-1.16.5-to-1.18.2%5D
- https://github.com/mezz/JustEnoughItems/wiki/Creating-Plugins-%5BMinecraft-1.16.5-to-1.18.2%5D
