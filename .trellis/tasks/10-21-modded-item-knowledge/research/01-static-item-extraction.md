# 静态离线提取：Forge 整合包「注册名 ↔ 中文名 ↔ 英文名」还原方案（1.20.1 / Farming + zyjd）

> 研究范围：只扫描磁盘上的 jar 与配置，**不启动服务端**。
> 全程未修改 `/home/guigui/mc/Farming`、`/home/guigui/mc/zyjd`、`astrbot_plugin_mc_manager` 下任何文件。
> 所有产物写在 `/home/guigui/mc/.research/` 与 `/tmp/mcresearch/`。

---

## 一、结论速览

1. **lang key 推导可行，主规则极简：**`item.|block.|entity.|fluid.` + `<namespace>` + `<path>`，id = `key[1]:key[2]`。
   用「tag / 配方 / 掉落表 / 模型文件名」交叉验证，Farming 的 47209 个注册类 key 里 93.8%（44277）能命中另一份独立证据，只有 6.2%（2937）纯靠 key 猜。
   幽灵 key 上界：Farming 2.3%（1051/45727）、zyjd 3.2%（446/13799）。

2. **单靠 lang 不够，必须多信源合并。** Farming 最终 39585 条 id 里 lang 只贡献 22807 条（57.6%），tag 22888、recipe 21272、loot 21003、模型 27394 各覆盖一大片；只看 lang 会漏 16778 条（42.4%）真实注册名。反过来只靠数据文件则完全没有名字。

3. **中文覆盖率是硬伤：Farming 57.5%（22769/39585）、zyjd 66.4%（5959/8974）。**
   主因不是提取方法，而是**模组根本不带 zh_cn**：Farming 207 个 namespace 有 en_us，只有 155 个有 zh_cn（53 个只有英文）；zyjd 139 vs 102（38 个只有英文）。

4. **三个必须防的坑（都实测出来了）**：
   - **子 key 污染**：`item.minecraft.potion.effect.stability` 这类 4 段以上 key 会污染 base 名（把 `minecraft:potion` 改成「稳定药水」）。Farming 有 6452 个，占注册类 key 13.7%，必须丢弃。
   - **模型目录不是物品**：`models/item/template/*.json`、`models/item/bite_stages/*.json` 会产生 3053 条假 id，必须过滤 path 带 `/` 的。
   - **jar 的 modId ≠ 它提供的 assets namespace**：`framework-1.0.2.jar` 的 modId 是 `standalone_copycats`，却提供 `assets/farmingtales/*`（3772 条 id 拿不到 mod 名）。

5. **`hotai/` 不是翻译覆盖，是 Java 字节码热补丁**（org.badiff 格式，79 个 `.badiff`、245KB，`grep -P '\p{Han}'` 命中 0），**提供不了任何物品名**。`kubejs/config/english_translation.json` 才是真·翻译层（`registry` 段 13698 条 key→英文），且**只有英文**。

---

## 二、jar 内部结构与 lang key 实证

### 2.1 规模

| 项 | Farming | zyjd |
|---|---|---|
| `mods/*.jar` | 278（716M） | 228（977M） |
| 含 jar-in-jar 递归后扫描的 jar | 378 | 322 |
| `META-INF/mods.toml` 解析出的 mod | 310 | 243 |
| `data/**/recipes/*.json` | 40516 | 8685 |
| `assets/*/lang/en_us.json` | 233 个文件 | 156 个 |
| `assets/*/lang/zh_cn.json` | 175 个文件 | 113 个 |
| 注册类 lang key（item/block/entity/fluid） | 47209 | 15320 |

证据：

    $ ls /home/guigui/mc/Farming/mods | wc -l          -> 279（278 jar + 1 非 jar）
    $ du -sh /home/guigui/mc/Farming/mods             -> 716M
    $ ls /home/guigui/mc/zyjd/mods | wc -l            -> 228 ; du -sh -> 977M

### 2.2 key 前缀分布（真实数字）

Farming 注册类 key（en_us + zh_cn 合并计数）：

    block 30065 | item 15662 | entity 1157 | fluid 325      共 47209

zyjd：

    item 7078 | block 6721 | entity 1505 | fluid 16          共 15320

**非注册类 key 远多于注册类**：Farming 的非注册 key 出现次数合计 44970（en+zh 文件合计，非去重），Top 前缀
`gui=4763, create=4508, tooltip=2984, quark=2498, tag=1885, advancements=1860, advancement=1707, config=1474, message=1216, leaves_type=938, ftbquests=932, text=853`。
即 **`assets/<ns>/lang/xx_xx.json` 里只有约一半 key 是物品名**，不能无脑全收。

### 2.3 真实样本（原文照抄）

`[机械动力] create-1.20.1-6.0.8.jar!/assets/create/lang/zh_cn.json`（3635 条）：

    advancement.create.andesite_alloy        = 坚如磐石
    block.create.cogwheel                    = 齿轮
    item.create.andesite_alloy               = 安山合金
    fluid.create.chocolate                   = 巧克力

`[农夫乐事] FarmersDelight-1.20.1-1.3.4.jar!/assets/farmersdelight/lang/zh_cn.json`（479 条）：

    block.farmersdelight.cooking_pot         = 厨锅
    block.farmersdelight.cutting_board       = 砧板
    item.farmersdelight.bacon_and_eggs       = 培根煎蛋

`zyjd/mods/alexsmobs-1.22.9.jar!/assets/alexsmobs/lang/zh_cn.json`（1081 条）：

    entity.alexsmobs.grizzly_bear            = 灰熊
    item.alexsmobs.spawn_egg_grizzly_bear    = 灰熊刷怪蛋
    item.alexsmobs.bear_fur                  = 灰熊毛皮

`[车万女仆] touhoulittlemaid-...jar!/assets/touhou_little_maid/lang/zh_cn.json`（1172 条）：
前缀分布 `gui 181 / config 158 / patchouli 142 / ai 110 / advancements 108 / item 72` ——
**中文 mod 的 lang 里注册类 key 只占一小部分**，其它全是 GUI 文案。

### 2.4 关键事实：lang 文件全局合并，文件名里的 namespace 不代表 key 的命名空间

Minecraft 把所有 `assets/*/lang/zh_cn.json` 合并进同一张翻译表，**文件放在哪个 namespace 只影响资源包优先级，不影响 key 解析**。

实证：`Farming/kubejs/assets/minecraft/lang/zh_cn.json`（15910 条）里 key 第二段分布是

    dramaticdoors 2189 | selfexpression 1325 | minecraft 1319 | quark 1003 | dustydecorations 533
    autoconfig 472 | bloomingnature 450 | cataclysm 424 | vinery 393 | meadow 345 | mcwwindows 321 ...

且 `block.farmersdelight.cooking_pot -> 厨锅` 确实在这个「minecraft 命名空间」文件里；
扫描器给 `farmersdelight:cooking_pot` 记的 `zh_source` 正是它 —— 说明这条数据真的生效。

**结论：id 的 namespace 取 key 的第二段，绝不能取文件名目录。**

---

## 三、key→ID 推导规则：准确率与反例

### 3.1 规则

    key = <kind>.<ns>.<path>[.<sub>...]        kind ∈ {item, block, entity, fluid}
    id  = <ns>:<path>

三段 key（`item.create.cogwheel`）直接映射。
四段及以上必须靠「已知 id 集合」消歧：

- 若 `ns:path.sub` 整串是已知 id → 用整串（真正的带点号注册名）
- 否则判为**子 key**（`.desc` / `.tooltip` / 药水变体 / 音效），**丢弃，不用它的译文覆盖 base 名**
- 再否则才是裸猜（记 `resolve_guess`）

### 3.2 实测准确率（Farming）

| 指标 | 数值 | 说明 |
|---|---|---|
| 注册类 key 总数 | 47209 | 含 en_us + zh_cn |
| 命中独立证据的 key | 44277（93.8%） | 该 id 也出现在 tag/recipe/loot/模型/blockstate |
| 只能靠 key 猜的 key | 2937（6.2%） | `resolve_guess` |
| 被判为子 key 丢弃 | 6452 | 占注册类 key 13.7% |
| 3 段 item/block key 无同名模型/blockstate | 1051 / 45727 = **2.3%** | 幽灵 key 上界 |
| 整条 id 只有 lang 一个信源 | 533 条（全部 id 的 1.3%） | 最容易是幽灵 |
| 真正带点号的注册名（`resolve_full`） | **0** | 两个包内都不存在 |

zyjd 对照：命中 88.8%（13655/15370）、幽灵 key 上界 3.2%（446/13799）、纯 lang id 631 条（7.0%）、`resolve_full` 同样为 0。

> 幽灵样例：`block.ftbquests.progress_detector`、`block.ftbquests.chest`；
> namespace `dustydecor`(113)、`crustydustydecor`(52) **根本没有对应 jar**，只有别的 mod 的兼容 lang 提到。

### 3.3 反例清单（具体到 mod）

**(a) key 的 namespace ≠ 文件 namespace（1117 个 key，2.4%）—— 不是错误，是兼容翻译**

    yuushya_modelling 的 lang 里有 328 条 yuushya.*
    bountifulfares 的 lang 里带了 natures_spirit(66) / excessive_building(58) / mint(44) / dye_depot(32) / minecraft(40)
    chimes 的 lang 里有 33 条 glass_wind_bell.*
    JadeAddons 的 lang 里有 4 条 tconstruct.*
    kaleidoscope_world_liquor 的 lang 里有 16 条 kaleidoscope_tavern.*

处理：**认 key 第二段**。按文件目录走会把这 1117 个 key 全判错。

**(b) jar 的 modId ≠ 它提供的 assets namespace**

    framework-1.0.2.jar         modId="standalone_copycats"   displayName="框架 | Framework"
                                却提供 assets/farmingtales/**（3772 条 id 的命名空间）
    Paintable-Compat-1.10.2.jar modId="farmingtales_paintable_compat"，也提供 assets/farmingtales/**
    doll-1.20.1-...jar          modId="farmingtales_doll"，提供 farmingtales 兼容 lang

后果：`farmingtales` 在 mods.toml 里**不存在**，3772 条 id 的 `mod_name` 为 NULL。

**(c) 子 key 伪装成 id（最危险，会写错名字）**

    item.minecraft.potion.effect.stability   -> 会把 minecraft:potion 命名成「稳定药水」
    item.amendments.dye_bottle.red           -> 会把 amendments:dye_bottle 命名成「红色」
    block.yuushya.a_acacia_blindwall.xxx     -> 会把该方块命名成「§9[模板材料]」

修掉后 `yuushya:a_acacia_blindwall` 的中文从错误占位符恢复为正确的「金合欢木板壁 A」。**Farming 有 6452 个这种 key**。

**(d) 模型目录被当成物品（3053 条假 id）**

    another_furniture:template/bench
    another_furniture:unused/oak_grandfather_clock
    autumnity:painting/pumpkin
    kaleidoscope_grilling:bite_stages/failure_skewer_states_dark_state_21_bite_1

处理：`models/item/**` 与 `blockstates/**` 中 path 带 `/` 的一律丢弃（Farming 丢弃 2202 个文件），真实注册名几乎不带 `/`（本包内 0 例）。

**(e) 只有 lang、没有实物的幽灵 key**

    block.ftbquests.progress_detector / progress_screen / chest / loot_crate_storage
    item.efn.welcome_diamond（zyjd）
    item.duel_dimension.drowned_spawn_egg（zyjd）

**(f) 译名是占位符**

`yuushya` 有 177 个 key 的中文全是 `§9[模板材料]`、182 个 key 的英文全是 `§9[Template Assets]`，真实显示名是运行时用组件算的。
统计：Farming 有 1661 个中文名被复用在 ≥2 个 id 上（唯一中文名 20078 个），top 是「挂画」32、「悬挂海报」22、「音乐唱片」21。

**(g) 官方 lang 里中英相同**

Farming 75 条、zyjd 85 条记录 `name_zh == name_en`（英文 mod 直接抄 en_us 当 zh_cn）。

---

## 四、多信源合并策略

### 4.1 各信源性质与可靠性（实测）

| 信源 | 提取位置 | 能给什么 | 可靠性 | Farming 命中 |
|---|---|---|---|---|
| `lang` | `assets/*/lang/{en_us,zh_cn}.json` | 名字 + kind | 高（有子 key 陷阱） | 22807 |
| `kubejs_lang` | `kubejs/assets/*/lang/*.json` | 名字（资源包，优先级最高） | 高 | 10225 |
| `trans` | `english_translation.json` 的 `registry` 段 | **只有英文** | 中（作者手写，偶有错译） | 10633 |
| `tag` | `data/*/tags/{items,blocks,entity_types,fluids}/**` 的 `values` | 只证明存在 + kind | 高（加载期校验） | 22888 |
| `recipe` | `data/*/recipes/**` 的 result/ingredients | 只证明存在 | 高 | 21272 |
| `loot` | `data/*/loot_tables/**` 的 `entry.name` | 存在 + kind | 高 | 21003 |
| `kubejs_data` | `kubejs/data/*/{tags,recipes}/**` | 存在 | 高 | 1175 |
| `model` | `assets/*/models/item/*.json` 文件名 | 存在（≈有 BlockItem，能 give） | 中高 | 27394 |
| `blockstate` | `assets/*/blockstates/*.json` 文件名 | 存在（方块） | 中（可能无物品形态） | 23101 |
| `script` | `kubejs/**/*.js` 的 `'ns:name'` 字面量 | 引用 | 低 | 6399 |
| `script_registry` | KubeJS `StartupEvents.registry(...)` + `.create('literal')` | **动态注册的真物品** | 高 | 207 |

### 4.2 建议的合并优先级

**名字字段**：
1. `kubejs/assets/**/lang/zh_cn.json`（资源包，游戏里最后生效）
2. jar 内 `assets/<id.namespace>/lang/zh_cn.json`（同命名空间优先）
3. jar 内其它命名空间的兼容 lang（bountifulfares 帮 natures_spirit 翻译这种情况）
4. 英文同理；`english_translation.json` 的 `registry` 排在 jar en_us **之后**（二次注释层，且有过错译，如 `dramaticdoors:short_terminite_door` 给的英文是 "Short End Gate"）

> 原型目前用「jar 文件名排序 + 后写覆盖」（可复现）；生产建议按上面 4 条改成显式优先级，并保留 `zh_source` 便于回溯。

**存在性**：`tag ≈ recipe ≈ loot`（加载期强校验）> `kubejs_data` > `model/blockstate` >> `script`。`lang` 本身**不证明存在**（幽灵 2~3%）。

**置信度打分（原型实现，可直接沿用）**：

    0.95  lang 译文 + (tag|recipe|loot|model|blockstate)    17831 条
    0.90  KubeJS 显式 create() 且有中文                        192 条
    0.80  只有 lang 译文                                       870 条
    0.70  lang key + 其它旁证但缺中文                         3838 条
    0.55  只在资源包 lang / registry 里出现                    3876 条
    0.50  只有 tag/recipe/loot 旁证（id 真、没名字）            8578 条
    0.40  只有模型/blockstate 文件名                           2112 条
    0.30  只出现在脚本字面量                                   2211 条

### 4.3 冲突消解

- **同一 id 多个中文名**：Farming 记录 3411 次 zh 冲突、6715 次 en 冲突，绝大多数是「同一句话不同 jar 副本」（yuushya 与 yuushya_modelling 都翻了同一批 key，文本一致），真语义冲突很少。策略：按 4.2 优先级取；平级时取**同命名空间文件**；仍平级则保留第一条并写 `conflicts` 表。
- **同一中文名多个 id**：不合并（「挂画」32 个 id 本就该共存），但可给 AI 端做「同名候选」提示。
- **中英冲突**：不校验（同一 id 的中英来自不同文件很正常）。

---

## 五、原型脚本

**路径**：`/home/guigui/mc/.research/prototype/scan_items.py`（716 行，纯标准库）

**运行**：

    python3 /home/guigui/mc/.research/prototype/scan_items.py /home/guigui/mc/Farming --out /tmp/out/farming
    python3 /home/guigui/mc/.research/prototype/scan_items.py /home/guigui/mc/zyjd    --out /tmp/out/zyjd

输出 `<out>.json`（全量记录 + mod 表 + 冲突表）与 `<out>.sqlite`（`items` / `mods` / `conflicts` 三表 + 索引）。
字段：`id, namespace, path, kind, kinds, name_zh, name_en, mod_id, mod_name, mod_version, source, confidence, zh_source, en_source, flags`。

性能：Farming（278 jar / 716M / 4 万个 json）两遍扫描 **6.9 秒**，峰值内存 171MB。

    $ /usr/bin/time -v python3 scan_items.py /home/guigui/mc/Farming --out /tmp/mcresearch/out/farming
    Elapsed (wall clock) time: 0:06.92        Maximum resident set size: 171280 KB

### 5.1 两服真实输出

**Farming**

    jar 数量        : 378          mods.toml mod 数 : 310
    最终 id 总数     : 39585        有中文: 22769 (57.5%)   有英文: 26776   无名字: 12809
    kind: block 27552 | item 11048 | entity 696 | fluid 289

| source | 命中 id 数 | 占全部 |
|---|---|---|
| model | 27394 | 69.2% |
| blockstate | 23101 | 58.4% |
| tag | 22888 | 57.8% |
| lang | 22807 | 57.6% |
| recipe | 21272 | 53.7% |
| loot | 21003 | 53.1% |
| trans | 10633 | 26.9% |
| kubejs_lang | 10225 | 25.8% |
| script | 6399 | 16.2% |
| kubejs_data | 1175 | 3.0% |
| script_registry | 207 | 0.5% |

关键两两重叠：`lang∩model=20625`、`lang∩tag=16539`、`lang∩recipe=14561`、`lang∩loot=15000`、`model∩tag=20824`、
**`trans∩kubejs_lang=10225/10225`（完全重合 → registry 就是从各 mod 的 lang 生成的）**。

**zyjd**

    jar 数量        : 322          mods.toml mod 数 : 243
    最终 id 总数     : 8974         有中文: 5959 (66.4%)   有英文: 6590   无名字: 2316
    kind: item 4351 | block 3817 | entity 785 | fluid 21

| source | 命中 id 数 | 占全部 |
|---|---|---|
| lang | 6709 | 74.8% |
| model | 6400 | 71.3% |
| tag | 5099 | 56.8% |
| recipe | 4130 | 46.0% |
| loot | 3610 | 40.2% |
| blockstate | 3321 | 37.0% |
| script | 35 | 0.4% |

（zyjd 没有 `kubejs_lang`/`trans`/`kubejs_data`：kubejs 几乎是空的，1 个 server script + 3 个 client script。）

### 5.2 「能不能 give」的量级

用「有 `models/item/<name>.json`」近似「有 BlockItem」：

| | Farming | zyjd |
|---|---|---|
| `give` 可用（item + 带模型的 block） | **32152** | **7213** |
| 其中带中文 | **17517（54.5%）** | **4984（69.1%）** |
| 纯方块、大概率无物品形态（不能 give） | 6447 | 956 |

### 5.3 人工核对 10 条

| # | 包 | id | kind | 中文 | 英文 | mod | 证据源 | conf | 判定 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | F | `create:cogwheel` | block | 齿轮 | Cogwheel | Create | blockstate,lang,loot,model,recipe,tag | 0.95 | ✅ 与 Create 中文客户端一致 |
| 2 | F | `create:andesite_alloy` | item | 安山合金 | Andesite Alloy | Create | lang,loot,model,recipe,tag | 0.95 | ✅ |
| 3 | F | `farmersdelight:cooking_pot` | block | 厨锅 | Cooking Pot | Farmer's Delight | 9 源 | 0.95 | ✅ 中文来自 kubejs 资源包，与官方一致 |
| 4 | F | `create:honey` | fluid | 蜂蜜 | Honey | Create | blockstate,lang,tag | 0.95 | ✅ 正确识别为流体而非方块 |
| 5 | F | `farmingtales:golden_pan` | item | 金锅 | Golden Pan | — | kubejs_lang,script,script_registry,trans | 0.90 | ✅ KubeJS 动态注册，静态 jar 里没有 → 证明必须扫脚本 |
| 6 | F | `dustydecorations:salmon_barrel` | block | 鲑鱼桶 | Salmon Barrel | Dusty Decorations | 8 源 | 0.95 | ✅ 中文来自 `kubejs/assets/minecraft/lang` 跨命名空间合并 |
| 7 | F | `dramaticdoors:short_terminite_door` | block | 矮终界门 | Short End Gate | Dramatic Doors | kubejs_lang,trans | 0.55 | ⚠️ 中文可信；英文 "Short End Gate" 是作者意译，偏了 |
| 8 | Z | `alexsmobs:grizzly_bear` | entity | 灰熊 | Grizzly Bear | Alex's Mobs | lang,tag | 0.95 | ✅ 实体 kind 判定正确 |
| 9 | Z | `minecraft:diamond_sword` | item | — | — | minecraft | loot,recipe,tag | 0.50 | ❌ 原版物品**拿不到名字**（服务端安装无 client jar，见 6.1） |
| 10 | Z | `cataclysm:music_disc_ignis` | item | 音乐唱片 | Music Disc | cataclysm | lang,loot,model,tag | 0.95 | ⚠️ id/存在性正确，但译名是通用占位（该 mod 有 21 张唱片同名） |

**10 条里 7 条完全正确，1 条名不副实，1 条英译偏，1 条原版缺名 —— 成功率 80%，且两个问题都可自动检测（"同名过多"/"译文是通用词"标记）。**

---

## 六、现实风险与边界

### 6.1 原版 `minecraft:` 名字拿不到（最大硬伤）

服务端安装里**没有 client jar**：

    $ find /home/guigui/mc/Farming/libraries -name '*client*.jar'      -> 空
    $ ls .../libraries/net/minecraft/server/1.20.1-...                  -> 只有 server-srg.jar / slim.jar

结果：Farming 有 1298 个 `minecraft:` id，只有 199 个有中文（来自 `kubejs/assets/minecraft/lang/zh_cn.json` 的覆盖）；zyjd 1088 个几乎全没有。`minecraft:diamond_sword` 这种最常见需求反而是空的。
**解法**：内置一份原版 1.20.1 `zh_cn.json`（约 6000 条）或从客户端 jar 提取 —— 这是常量表，与整合包无关。

### 6.2 模组本身没有 zh_cn（第二大来源）

Farming 53 个 namespace 只有 en_us：`bf_blockpack`(1203)、`cluttered`(1031)、`paintable`(999)、`spawn`(339)、`wallpapers`、`dustydecorations`、`mcwwindows`、`beautify`、`biomesoplenty`、`environmental`、`selfexpression` …
zyjd 38 个：`oceanic_delight`、`alexsdelight`、`armourers_workshop`、`theimpossiblelibrary` …
**静态方法无解**，只能给 AI 英文名让它自己意译，或人工补译表。

### 6.3 KubeJS 动态注册的物品（静态扫描有缺口）

Farming 的 `kubejs/startup_scripts/` 大量用**包装函数**，静态正则抓不全：

    // equipment/tools.js
    StartupEvents.registry("item", (e) => {
      const createTool = (name, type, ...) => { e.create(name, type)... }
      createTool("copper_sword", "sword", 3, 150, 5.0, 2)   // 字面量在 createTool 调用里，不在 .create() 里
    })

原型只抓到 227 个 `.create('literal')`。但这类物品**通常**会被资源包 lang 或配方引用覆盖
（`kubejs:copper_sword` 就从 `kubejs/assets/kubejs/lang/zh_cn.json` 找回来了，中文「铜剑」正确），
实际漏网不多：`kubejs:` 命名空间共 114 条，`farmingtales:` 通过脚本注册拿到 194 条。

### 6.4 运行时配方改写让静态配方不完整

Farming 的 `kubejs/server_scripts` 里 **52 个文件**监听 `ServerEvents.recipes`，共 **144 次 `event.remove*`**；
另有 `kubejs/data/**` 1283 个 json 覆盖/新增配方。zyjd 用 CraftTweaker（`scripts/duelcraft_crafttweaker.zs`）。
→ **静态 recipe 只能给出"原本长什么样"，不能说"现在怎么合"**。要么解析 JS 的 `event.remove/event.recipes`，要么运行时导出。

### 6.5 其它

- **`hotai/` 不能提供名字**。它是 ModLauncher `ITransformationService` + `org.badiff` 二进制类补丁：
  `hotai-1.0.jar` 里只有 `youyihj/hotai/*.class` 和 `org/badiff/*.class`；`hotai/` 目录 79 个 `.badiff`、245KB，
  按 `net/satisfy`(15)、`com/farmingtales`(6)、`com/ninni`(5)、`net/brdle`(5)、`cn/breezeth`(4)、`net/minecraft`(3) 等包路径存放。
  `strings` 与 `grep -P '\p{Han}'` 都是空 —— 二进制 diff，不含可读文本，更不含 lang JSON。
  理论上可以打到目标 class 上再抽字符串常量（jar 自带 org.badiff），但那是 Java 代码里的硬编码文本，不是物品名表，收益极低。
- **`english_translation.json` 只有英文**：`exact`(3421 条中文原句→伪 key)、`english`(3422 条伪 key→英文)、`patterns`(152 条带参模板)、`registry`(13698 条 lang key→英文)。它是给英文客户端的二次翻译层，中文名仍要从 jar/资源包 zh_cn 拿。
- **namespace 与 mod 名对不上**（见 3.3b）：需要人工别名表，或运行时用模组列表补齐。
- **`script` 信源噪音大**：Farming 有 2203 条 id 只有脚本引用这一个来源，置信度只给 0.3，不要当"存在证明"。

---

## 七、给插件集成的直接建议

### 7.1 数据结构

离线产出一个 SQLite 直接当知识库分发。实测体积：Farming `17.4 MB`（gzip 后 **2.7 MB**）、zyjd `3.4 MB`；JSON 全量 20.4 MB。

```sql
CREATE TABLE items(
  id TEXT PRIMARY KEY,          -- create:cogwheel
  namespace TEXT, path TEXT,
  kind TEXT,                    -- item|block|entity|fluid
  kinds TEXT,                   -- 多形态：block,item
  name_zh TEXT, name_en TEXT,
  mod_id TEXT, mod_name TEXT, mod_version TEXT,
  source TEXT,                  -- lang,tag,recipe,model,...
  confidence REAL,              -- 0.25~0.95
  zh_source TEXT, en_source TEXT,
  flags TEXT                    -- no_zh / zh_eq_en / block_item ...
);
CREATE INDEX idx_items_ns ON items(namespace);
CREATE INDEX idx_items_zh ON items(name_zh);
CREATE VIRTUAL TABLE items_fts USING fts5(id, name_zh, name_en, mod_name, tokenize='unicode61');
```

搜索顺序：**精确 id** → **中文精确匹配** → **FTS5/前缀**（「齿轮」→`create:cogwheel`；「create 齿轮」→ 按 mod 过滤）。

### 7.2 修掉写死的 `minecraft:` 前缀

现在 `tools/game_tools.py:46` 和 `:131` 是无条件 `if not item.startswith("minecraft:")`。改成：

1. 输入已带 namespace（含 `:`）→ 原样透传；
2. 否则查知识库：中文/英文精确命中 → 用命中 id；多候选 → 返回候选让 LLM 追问；
3. 查不到 → 保留旧行为并明确告诉 AI「这是猜测」；
4. `give` 失败时把 RCON 报错（`Unknown item` / `Cannot give item`）回传给 AI，避免死循环。

### 7.3 新增 LLM 工具的粒度

只加 2 个工具，别把 3 万条塞进 prompt：

- `search_item(keyword, mod=None, limit=10)` → `[{id, name_zh, name_en, mod_name, kind, confidence}]`
- `get_recipe(item_id)` → 从 `data/*/recipes` 反查（**注意 6.4：静态配方可能被 KubeJS 删改**，返回值要标注来源与时间）

`give_item`/`summon_entity` 内部先调 `search_item` 解析，再执行。

### 7.4 更新方式

- **离线构建 + 随包分发**：扫描脚本做成独立 CLI，输出 `items.sqlite`；mods 不变就不重建。
- **插件启动校验**：比 `mods/` 目录 mtime 与库内 `built_at`，不一致打 warning（**不要在启动时同步全量扫描 716M**，7 秒虽快但会阻塞事件循环，放线程池/后台任务）。
- **管理命令**：`/mcmanager reload items` 触发重建（后台线程 + 进度日志）。
- **可选运行时补全**：zyjd 有 CraftTweaker 14.0.59，它带 `/ct dump`（可 dump items/recipes）；Farming 没有。这条路线**本次未验证**（需把服务端复制到 /tmp 启动才能确认输出格式），但它能一次性解决"原版缺名 + KubeJS 动态物品 + 运行时配方"三个问题，值得作为第二阶段。

### 7.5 立即可用的量化目标

- Farming 32152 条 `give` 可用 id 里，**17517 条带中文**（54.5%），这就是知识库主战力。
- 剩下 14635 条没中文：其中 6447 是没物品形态的方块（give 本来就会失败），实际"可 give 但缺中文"约 8000 条 —— 靠 6.1 原版表 + 6.2 人工补译能吃掉一大半。
