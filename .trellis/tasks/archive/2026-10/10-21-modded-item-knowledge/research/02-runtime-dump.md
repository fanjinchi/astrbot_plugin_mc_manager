# 02 - 运行时权威导出实测（Forge 1.20.1 服务端把注册表和配方吐出来）

> 实验对象：/home/guigui/mc/zyjd 的**副本**（228 mods），复制到 /tmp/mc-rd/zyjd 后启动，原目录全程只读。
> Java：/usr/lib/jvm/zulu-17-amd64/bin/java（1.20.1 必须用 17）。RCON 端口 25575，游戏端口 25599。
> 说明：SA2 子代理在最终报告落盘前被中断，本文由主会话基于其**实测产物**（.research/runtime-dump/）整理，所有数字均可从产物复算。

---

## 结论速览

1. **不需要写服务端 mod，也不需要 mixin。** 往 kubejs/server_scripts/ 丢一个脚本注册 /researchdump，遍历 BuiltInRegistries + server.recipeManager，就能把全量数据打成 JSONL。
2. **物品/方块/实体/流体：完美。** item 6759 / block 4247 / entity 931 / fluid 44，每行含 id、tkey（语言键）、resolved（服务端英文显示名）、stack（SNBT）。
3. **配方也能拿，覆盖率 93.2%：** 6231 条里 5805 条 inputs+outputs 齐全，22,190 个输入槽中 3,587 个是 tag（保留为 `{tag:...}`，没被展开）。关键是必须用 `Ingredient.toJson()`，用 getItems() 只能拿到空数组。
4. **但配方类型只覆盖 35 种**（静态扫描能见 91 种）。少掉的是每类只有个位数条目的稀有类型，按条数算仍覆盖 93%。
5. **中文要靠 jar join：命中 69.4%**（11,937 个实体里 8,289 个 tkey 能在 jar 的 zh_cn 里找到）。英文 76.8%。缺口原因同静态路线：模组本身不带 zh_cn。
6. **/forge dump 在 47.4.0 不存在**；**/ct dump 需要在线玩家**（RCON 下报 'A player is required to run this command here'）；**/jei 在服务端无命令**。这三条已实测排除。

---

## 1. 实验服搭建（可复现）

```bash
# 复制（不复制 world/logs/jre/备份，保留运行必需文件）
mkdir -p /tmp/mc-rd && cp -a /home/guigui/mc/zyjd /tmp/mc-rd/zyjd

# 改副本配置
enable-rcon=true
rcon.password=test123
rcon.port=25575
server-port=25599
online-mode=false

# 启动（8G 堆，Java 17）
cd /tmp/mc-rd/zyjd
/usr/lib/jvm/zulu-17-amd64/bin/java -Xmx8G -Xms8G \
  @libraries/net/minecraftforge/forge/1.20.1-47.4.0/unix_args.txt nogui
```

启动到出现 `Done (` 约 3~4 分钟（228 mods，首次生成世界）。内存峰值约 7.8G。
随后把 `zz_research_dump.js` 放进 kubejs/server_scripts/，重启或 /reload 后执行 /researchdump。

---

## 2. 命令面实测（哪些能用、哪些不能用）

| 命令 | 结果 |
|---|---|
| /forge dump、/forge dump items | **不存在**（Incorrect argument） |
| /forge tags <registry> (list/get/query) | **可用** |
| /forge mods | 可用，输出 18,860 字符模组清单（含中文名） |
| /kubejs dump_registry minecraft:item | **可用**，205,893 字符纯文本 id 列表 |
| /kubejs dump_registry minecraft:entity_type | 可用，24,671 字符 |
| /kubejs dump_registry minecraft:recipe_serializer | 可用，3,285 字符（配方**类型**，不是配方实例） |
| /kubejs export | 可用，落盘 local/kubejs/export/（registries/ tags/ loot_tables/ mods.json，**无 recipes**） |
| /ct dump | **不可用**：'A player is required to run this command here' |
| /jei、/jei dump | **不存在**（JEI 是纯客户端 mod） |
| researchdump（自写脚本） | **可用**，即本文数据来源 |

---

## 3. 自写 KubeJS 脚本的关键技术点

```javascript
// 注册表遍历：直接用 Java.loadClass 拿 BuiltInRegistries
var BIR = Java.loadClass('net.minecraft.core.registries.BuiltInRegistries')
var C   = Java.loadClass('net.minecraft.network.chat.Component')

// tkey：这是最有价值的一列 —— 它直接告诉你该查 item. 还是 block. 前缀
var tid = it.getDescriptionId()        // 例: block.abnormals_delight.aspen_cabinet

// resolved：服务端实际生效的英文名（已应用所有语言覆盖）
var res = C.translatable(tid).getString()

// 配方输入：必须用 Ingredient.toJson()，不能用 getItems()
var opts = ings.get(k).toJson()        // {"tag":"forge:ores/x"} 或 {"item":"ns:id"}
```

**踩过的两个坑（都实测）**：
- `Ingredient.getItems()` 在 KubeJS 桥接下返回空数组 → 22,190 个槽全空。换成 `Ingredient.toJson()` 后正常，且 tag 原样保留。
- `recipe.getType().toString()` 直接 String 化会得到 `null`，要取 `ResourceKey` 再拼。

---

## 4. 产物与质量（zyjd，228 mods）

| 文件 | 行数 | 说明 |
|---|---|---|
| item.jsonl | 6,759 | id + tkey + resolved + stack(SNBT) |
| block.jsonl | 4,247 | id + tkey + resolved |
| entity.jsonl | 931 | id + tkey + resolved |
| fluid.jsonl | 44 | id |
| recipe.jsonl | 6,231 | id + type + serializer + out[] + in[][] |
| recipetype.jsonl | 37 | 每种类型的条数 |

配方质量：
- **5,805 / 6,231（93.2%）输入输出齐全**
- 无输入 425 条、无输出 220 条（集中在 aether:*、apotheosis:salvaging 等自定义配方类）
- 22,190 个输入槽：tag 型 3,587（16.2%）、item 型 16,363
- 覆盖 35 种 recipe type（静态扫描可见 91 种）；按**条数**仍覆盖 93%

配方类型 top：minecraft:crafting 3,918、stonecutting 1,005、farmersdelight:cutting 287、smelting 189、farmersdelight:cooking 114、aether:enchanting 111、apotheosis:salvaging 103。

---

## 5. 中文名 join 实测

把每个实体行的 tkey 拿去 jar 合并出来的 zh_cn 表里查：

| 指标 | 数值 |
|---|---|
| zh_cn 键总数（228 个 jar 合并） | 27,953 |
| en_us 键总数 | 28,026 |
| 无 zh_cn 的 jar | 127 / 228 |
| item+block+entity 实体总数 | 11,937 |
| **tkey → zh_cn 命中** | **8,289（69.4%）** |
| tkey → en_us 命中 | 9,170（76.8%） |

缺口样例（都是已知不带 zh_cn 的 mod）：`item.abnormals_delight.cherry_cookie`、`block.abnormals_delight.azalea_cabinet`。

**这个 69.4% 与静态路线独立算出的 66.4% 高度吻合** → 结论可信：中文覆盖率的天花板由模组决定，不是提取方法的问题。

---

## 6. 代价评估

| 项 | 实测 |
|---|---|
| 启动到可 dump | 3~4 分钟 |
| 内存峰值 | 约 7.8G |
| 全量 dump 耗时 | 秒级（RCON 返回 + 日志抓取） |
| 产物体积 | 约 4.5MB（6 个 jsonl） |
| 是否需常驻 | **不需要**，整合包更新时跑一次即可 |
| 副本磁盘占用 | 约 1.2G（不含 world） |

---

## 7. 对插件落地的结论

**运行时 dump 的价值排序**：
1. **物品/方块/实体/流体的权威 id + tkey + 英文名** —— 这是静态扫描给不了的（静态有幻影 key，且拿不到 tkey）。
2. **配方现状** —— 反映 KubeJS 增删和 conditional 求值后的真实结果，弥补静态的 121 条幽灵配方。
3. **模组清单** —— /forge mods 或 mods.json 给出 modid→中文名，用于"这是哪个模组的"。

**局限**：
- 依赖服务端装 KubeJS（无 KubeJS 的服退回纯静态）
- 配方类型只覆盖 35/91，稀有类型仍要静态 JSON 补
- 拿不到中文名（只能 join）
- 需要服主配合跑一次（或插件自己起一个临时服务端——不现实）

**推荐组合**：
- 服主跑一次脚本 → 得到 ids + recipes 快照
- 插件侧再扫一遍 mods/ 补中文名和稀有配方类型
- 两层按 id join，运行时优先（source='runtime'）

---

## 附录：产物路径

| 路径 | 内容 |
|---|---|
| .research/runtime-dump/item.jsonl 等 | 运行时 JSONL 产物 |
| .research/runtime-dump/all_zh_cn.json | 228 个 jar 合并的 zh_cn 表（27,953 键） |
| .research/runtime-dump/all_en_us.json | 合并的 en_us 表 |
| .research/runtime-dump/zh_sources.json | 每个 key 来自哪个 jar |
| .research/runtime-dump/zz_research_dump.js | dump 脚本原型（可复用） |
| .research/raw/*.txt | 各命令原始返回 |
