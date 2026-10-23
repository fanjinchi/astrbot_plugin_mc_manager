# 07 · 原版（vanilla）物品知识库：离线可行性、中文名来源、许可与落地方案

调研时间：2026-10-21。目标环境：MC 1.20.1 Forge，/home/guigui/mc/Farming（278 mods）、/home/guigui/mc/zyjd（228 mods）。
方法：全部结论均由 /tmp 下的临时脚本实测（脚本与产物保留在 `/tmp/vanilla/`），服务器目录只读，未改动任何文件。
引用的既有事实：research/01、02、05、06 与 prd.md（不重复验证）。

---

## 结论（推荐 + 兜底）

**一期可以做原版，而且不需要“内置一份 ~6,000 条常量表”。**

服务器安装里自带官方的 `assets/minecraft/lang/en_us.json`（在 Forge 的 `server-<ver>-extra.jar` / `-unpacked.jar` / bundler 内嵌 jar 里，不在 mods 里），把它当“ID 名册”反解，离线 0.11 秒就能得到 **1,369 个原版物品/方块 ID + 英文名**，对真实注册表 **精度 100%、召回 97.6%**（缺的 33 个在 1.20.1 里根本没有语言键）。中文名只差一份 **385 KB 的官方 `zh_cn.json`**，可以在重建时从 Mojang CDN 单文件下载（不随插件分发），或由服主放置。

| 方案 | 内容 | 结论 |
|---|---|---|
| **推荐 A（一期做原版）** | 离线读服务器安装里的 `en_us.json` 枚举 ID + 英文名；中文名重建时从官方 CDN 下载 `zh_cn.json`（sha1 校验、本地缓存、BMCLAPI/本地文件回退）；**仓库不内置任何 Mojang 资源** | 采用 |
| **兜底 B（不联网）** | 只建原版“ID + 英文名”（完全离线）；中文名由服主把 `zh_cn.json` 放进插件数据目录（与 `zh_cn_extra.json` 同一机制） | 断网/合规从严时采用 |
| **若最终一期完全不做原版** | 查询工具必须返回“知识库未收录原版”的明确文案，绝不能给空结果让 LLM 说“游戏里没有” | 见第 6 节 |

一句话更正 research/05 第 104-105 行：“服务端安装里没有 client jar”成立，但**服务端安装里有 en_us.json**；“必须内置 6,000 条常量表”不成立，ID 名册和英文名都能从服务端本地文件得到，只有中文名需要联网。

---

## 1. 原版 ID 全集：能拿到，零网络，0.11 秒

### 1.1 服务端安装里到底有什么（实测）

两台服的 `libraries/net/minecraft/server/` 内容完全一致：

| 文件 | 大小 | 是否含 `assets/minecraft/lang/en_us.json` | 是否含 `data/minecraft/**` |
|---|---|---|---|
| `1.20.1/server-1.20.1.jar`（Mojang bundler） | 47,791,053 B | 无（但内嵌 jar 有） | 无 |
| └ `META-INF/versions/1.20.1/server-1.20.1.jar`（内嵌） | 14,643,363 B | **有** | **有**（5,887 条） |
| `1.20.1-20230612.114412/...-slim.jar` | 9,414,196 B | 无 | 无 |
| `1.20.1-20230612.114412/...-srg.jar` | 14,086,905 B | 无 | 无 |
| `1.20.1-20230612.114412/...-extra.jar` | 5,229,189 B | **有** | **有**（5,887 条） |
| `1.20.1-20230612.114412/...-unpacked.jar` | 14,643,363 B | **有** | **有** |

- `extra.jar` 的 `assets/` 只有两项：`assets/.mcassetsroot`、`assets/minecraft/lang/en_us.json`（没有 zh_cn）。
- 两个服都有 `-extra.jar` / `-unpacked.jar`，所以目标环境（Forge 1.20.1）无需联网即可读。
- **这条与既有事实 5 不冲突**：事实 5 说的是 server-1.20.1.jar 本身不含 assets，正确；但 Forge 安装会把 Mojang 服务端的 data + en_us 拆到 extra/unpacked 里，bundler 内嵌的 vanilla jar 里也有。

复现：

```bash
python3 - <<'PY'
import zipfile
p="/home/guigui/mc/Farming/libraries/net/minecraft/server/1.20.1-20230612.114412/server-1.20.1-20230612.114412-extra.jar"
z=zipfile.ZipFile(p)
print([n for n in z.namelist() if n.startswith("assets/")])
PY
# ['assets/.mcassetsroot', 'assets/minecraft/lang/en_us.json']
```

### 1.2 枚举方法（三步，全部标准库）

1. **名册**：`en_us.json` 里 `item.minecraft.<id>` / `block.minecraft.<id>` 且**恰好两个点**的键 → 1,398 个候选 ID（去掉 `item.minecraft.potion.effect.*` 这类子键）。
2. **交叉验证**：候选 ID 是否出现在 `data/minecraft/**/*.json` 的 `"minecraft:<id>"` 引用里，或出现在 `srg.jar` 的 `Items.class` / `Blocks.class` 常量池字符串里。
3. **保留有名字的**：验证通过的 ID 才有语言键，也才有中英文名，正好是 KB 需要的集合。

实测（`/tmp/vanilla/vanilla_pipeline.py`，两台服输出一致）：

```
/home/guigui/mc/Farming
  jar: .../server-1.20.1-20230612.114412-extra.jar
  en_us: 6217 keys; plain ids: 1398; verified: 1369 (block-ish 987, item-ish 382)
  dropped (lang-only, no data/class evidence): 29
  timing: lang 0.016s, datapack 0.075s, classes 0.024s, total 0.115s
/home/guigui/mc/zyjd
  ... 同上，total 0.109s
```

准确率对照“真实注册表”——用 research/02 的 KubeJS 运行时 dump（该服真实 B 端注册结果）做 ground truth：

| 指标 | 数字 |
|---|---|
| 运行时原版注册项 | item 1,255 + block 1,003 → **1,402 个唯一 ID** |
| 离线得到 | 1,369（1,398 候选里 29 个被交叉验证剔除） |
| **精度** | 1,369 / 1,369 = **100%**（剔除的 29 个在运行时 dump 里 0 命中） |
| **召回** | 1,369 / 1,402 = **97.6%** |
| 缺失的 33 个 | 17 个锻造模板（`coast_armor_trim_smithing_template` 等）+ 16 个墙上旗帜（`*_wall_banner`）——**这 33 个在 1.20.1 的语言文件里根本没有键**，本来就没有名字可查 |
| 被剔除的 29 个 | 24 个旧版陶片别名（`angler_pottery_shard` 等，1.20.1 真实 ID 是 `*_pottery_sherd`）+ 5 个纯提示键（`sign`、`smithing_template`、`set_spawn`、`lodestone_compass`、`ominous_banner`），都不是注册名 |

**结论：1.20.1 里“有名字”的原版物品/方块 ID，离线可以 100% 拿全。**

### 1.3 其他候选源的实测结论（都不可用或更差）

| 候选 | 实测 | 判定 |
|---|---|---|
| `mappings.txt`（78,079 行） | 只有混淆名→Mojang 成员名的映射，没有注册名；文件头自带许可：“You may copy and use the mappings for development purposes, but you may not redistribute the mappings complete and unmodified.” | **不可用**（拿不到 `stone` 这类注册名，且自身禁止再分发） |
| 纯 datapack 引用（不看 class 常量池） | `plain ∩ refs` = 1,274；`Items.class` 常量池再补 95 个（刷怪蛋等） | 可用但少 95 个 |
| 只靠 `en_us` 键（不做交叉验证） | 1,398 个，其中 29 个是伪 ID | 少写 40 行代码，但会给 LLM 29 个坏 ID |
| KubeJS 运行时 dump | `item.jsonl` 6,759 条中 1,255 条 vanilla、`block.jsonl` 4,247 条中 1,003 条 vanilla，**ID 全，但只有英文 `resolved` 名**；`all_zh_cn.json` 里 `item.minecraft.*` 只有 326 个键（几乎全是 `potion.effect.*`，纯普通键只有 2 个） | 只能补 ID/英文名，解决不了中文（与事实 6 一致） |
| mods 里的 `assets/minecraft/lang/en_us.json` | Farming 278 个 jar 扫描 0.74s：只有 1 个 jar 带 `assets/minecraft/lang/en_us.json`（`[传奇怪物] legendarymonsters`），zh_cn 为 0 | 不是可靠来源 |

---

## 2. 原版中英文名

### 2.1 英文名：服务器本地就有，且与官方客户端一致

- 服务端 `extra.jar` 里的 `assets/minecraft/lang/en_us.json`：**386,499 字节，6,217 条**（item 585 / block 1,656）。
- 与官方 1.20.1 客户端 `en_us.json` **逐字节相同**：两者 sha1 均为 `701d1f2bf7215aaaefbfd1a52a0c44077365a4a2`（对照来源：版本化镜像 `https://cdn.jsdelivr.net/gh/InventivetalentDev/minecraft-assets@1.20.1/assets/minecraft/lang/en_us.json`，386,499 B / 6,217 条）。
- 结论：**英文名 0 成本、0 网络、无需 client.jar**。

### 2.2 中文名：官方 CDN 可以“只下一个文件”

官方链路（1.20.1 实测，curl/urllib）：

```
GET https://launchermeta.mojang.com/mc/game/version_manifest_v2.json        278,138 B
  → 1.20.1 条目: https://piston-meta.mojang.com/v1/packages/38d412af3b247e485c7f7e50ac25febc4e79ab1d/1.20.1.json   34,974 B
  → assetIndex: {"id":"5","size":413067,"url":"https://piston-meta.mojang.com/v1/packages/8a45c6be38ac9486b04944bffcb96f8aae1b0649/5.json"}
GET .../5.json                                                            413,067 B
  → objects["minecraft/lang/zh_cn.json"] = {"hash":"561ed78...","size":562116}
GET https://resources.download.minecraft.net/56/561ed7800004b882b8eeb032ffbe2bf03895bb44   562,116 B
```

实测成本（`/tmp/vanilla/dl_lang.py`，含 sha1 校验）：

| 场景 | 耗时 | 流量 | 请求数 |
|---|---|---|---|
| 冷启动（manifest→version→index→object） | **4.41 s** | 1,288,295 B | 4 |
| 全部命中缓存 | 0.01 s | 0 | 0 |
| 只刷新 lang（index 已缓存） | **1.21 s** | 562,116 B | 1 |

**轻量路径的答案：**

- `zh_cn.json` **可以**只下这一个对象（上面的实测），不需要整个 client.jar。
- `en_us.json` **不在 asset index 里**：该 index 的 `minecraft/lang/` 共 142 个文件，`en_au/en_ca/en_gb/en_nz/en_pt/en_ud/enp/enws` 都在，**唯独没有 en_us**；`client.jar`（23,028,853 B）里 `assets/minecraft/lang/` 只有 1 个文件就是 `en_us.json`（386,499 B / 6,217 条）。所以“官方只下两个 lang”做不到 en_us，但 en_us 也不需要下——服务器安装里已经有了。

**本环境的异常（重要，必须写进设计）**：按官方 asset index 下到的 `zh_cn.json` 是 **562,116 B / 8,655 条**，内容包含 `mace`（重锤）、`crafter`（合成器）、`pale_oak`（苍白橡木）、`resin_brick` 等 1.20.1 之后的键；同一次请求的 asset index 里连 `minecraft/textures/block/stone.png` 都没有（index 只有 3,598 个对象、素材只有 sounds + GUI 贴图 + lang）。也就是说：**这个环境下“按版本号下载”拿到的不是严格的 1.20.1 资源**。用版本化镜像交叉验证，真正的 1.20.1 `zh_cn.json` 是：

- **393,625 字节（385 KB）、6,215 条**（item 585 / block 1,656），键集与服务器 `en_us` 只差 2 条，不含任何 1.20.1 之后的物品。

→ 设计上不要把“下载文件的内容/条数”当作版本正确性的证据；**只把 zh_cn 当字典按已有 ID 取键**，这样下载到更新版本的 lang 也不会带进脏 ID。

### 2.3 中文名覆盖率

用 1,369 个 ID 去真 1.20.1 `zh_cn.json` 取键（`block.minecraft.<id>` 或 `item.minecraft.<id>`）：

- **1,369 / 1,369 = 100%** 命中；本环境那份 8,655 条的新版 lang 同样 100% 命中（键集是超集）。
- 抽样：`minecraft:stone` → 石头；`minecraft:diamond_block` → 钻石块；`minecraft:acacia_boat` → 金合欢木船。

---

## 3. 许可与合规

### 3.1 官方原文（两条，直接引用）

**Minecraft EULA** — <https://www.minecraft.net/en-us/eula>

> “However, you must not distribute anything we've made unless we specifically agree to it. By ”distribute anything we've made“ what we mean is: **give copies of our game software or content to anyone else**; make commercial use of anything we've made; …”
>
> “And so that we are crystal clear, ”the game“ or ”what we have made“ includes, but is not limited to, the Services, plus any other games we might publish in the future. It also includes updates, patches, downloadable or Marketplace content, add-ons, or modified versions of a game, **part of those things**, merchandise, audio-visual content, or anything else we've made.”
>
> “we retain ownership of our Minecraft intellectual property, which includes the game itself (including its content like the textures of our …)”

（同一页还有一句支持“做工具”的：“You may develop tools, plug-ins and services as long as they do not seem official or approved by us…”，但它不构成对分发游戏内容的许可。）

**Minecraft Usage Guidelines** — <https://www.minecraft.net/en-us/usage-guidelines>

> “Our assets, we mean the code, software, graphics, textures, images, models, sounds and other audio from any of our games and any videos or screenshots taken from our games”

> “If you are using any part of any name, any part of our brand, or any of our assets, then: … **redistribute our games or any alterations of our games or game files**”（属于“do not”清单）

> “All rights (including copyright, trademark rights, and related rights) in the name, brand, assets, and any derivatives are and will remain owned by Mojang and Microsoft”

判断依据：语言文件是游戏内容/资源（`assets/minecraft/lang/*.json` 属于 game files/assets），EULA 的“give copies of our game software or content to anyone else”和 Guidelines 的“redistribute … game files”都覆盖它；**没有**任何条款允许再分发语言文件。Guidelines 的 assets 定义列举的是 code/software/graphics/textures/images/models/sounds，没有逐字列出“翻译文本”，但“code, software … from any of our games”与 EULA 的“content / part of those things”足以覆盖。

### 3.2 三种做法逐条判断

| 做法 | 判断 | 说明 |
|---|---|---|
| **(a) 仓库内置 `zh_cn.json` + `en_us.json` 常量表** | **不合规，不建议** | 这就是“give copies of our game content to anyone else”/“redistribute … game files”。插件免费开源不等于获得许可（再分发禁令与是否收费无关）。即使只放“翻译文本”也是 Mojang 的 content。 |
| **(b) 运行时从官方源下载，不随插件分发** | **风险低，可用** | 下载发生在服主自己的机器、源是官方 CDN、缓存只落本地数据目录，不构成再分发；与官方启动器下载 assets 的行为同类。要求：不把缓存/清洗后的表提交进仓库、不对外提供镜像、README 说明来源与“仅本地使用”。 |
| **(c) 服主自备客户端 jar / assets 目录** | **风险最低，但要注意路径** | 服主本来就有许可，插件只读本地文件。**坑：`client.jar` 里只有 `en_us.json`，没有 zh_cn**（实测 23 MB 的 client.jar 里 `assets/minecraft/lang/` 只有 1 个文件）；`zh_cn.json` 在 `.minecraft/assets/objects/<hash前2位>/<hash>`（需要 index 才知道 hash）。所以“给个 client.jar”只能补英文；中文要么让服主导出一份 `zh_cn.json` 放到插件数据目录，要么走 (b)。本机没有 `~/.minecraft`，这条未能在真实客户端目录上验证（见第 7 节）。 |

### 3.3 CFPA 有没有“单独的原版翻译包”：没有

- CFPAOrg 31 个仓库（`GET https://api.github.com/orgs/CFPAOrg/repos?per_page=100`）里没有任何“原版翻译”仓库；只有模组汉化、整合包手册、术语库、字体修正等。
- `Minecraft-Mod-Language-Package` 仓库里确实有 `projects/assets/minecraft/`，但按版本目录（1.16/1.18/1.19/1.20/1.21/26.1）**只放字体修正**：`1.20/minecraft/` 下只有 `README.md`、`LICENSE`（MIT，CFPA 自己的文件）、`font/`、`packer-policy.json`，**没有 lang**；README 明说“该命名空间存放了用于汉化资源包的字体修正包”。
- 唯一的原版 lang 痕迹是 `projects/assets/minecraft/1.12.2/minecraft/lang/zh_cn.lang`，实测内容是 **1 个字节的换行**（占位文件）。
- 成品包 `/tmp/cfpa-1-20.zip`：1,025 个条目、608 个命名空间，`pack.mcmeta` 为 `pack_format 15`（1.20.1）；`assets/minecraft/` 下只有 `font/` 和 `textures/font/`，**没有任何 `assets/minecraft/lang/*`**（与事实 4 一致）。

**结论：原版中文名只能来自 Mojang 官方资源，CFPA 帮不上忙，没有“合规的原版翻译包”可用。** 这直接决定了第 4 节的方案选择。

---

## 4. 推荐方案与成本

### 4.1 推荐：A（离线枚举 + 运行时下载中文，不内置资源）

数据流（在 design 的 builder 里加一段，先于 mods 扫描或与之并行）：

```
<mc_server_dir>/libraries/net/minecraft/server/*/server-*-extra.jar（或 -unpacked.jar，或 bundler 内嵌 jar）
        │  assets/minecraft/lang/en_us.json  (386 KB / 6,217 条)
        ├─→ ID 名册：item.minecraft.* / block.minecraft.* 且恰好两个点 → 1,398
        ├─→ 交叉验证：data/minecraft/**/*.json 的 "minecraft:<id>" ∪ Items/Blocks.class 常量池 → 1,369
        │        （精度 100%，召回 97.6%；缺的 33 个无语言键）
        ├─→ 英文名：同一个 en_us.json
        └─→ 中文名：zh_cn.json（下载/服主提供）按 "block.minecraft.<id>" → "item.minecraft.<id>" 取键，命中 1,369/1,369
```

- **数据量**：
  - 仓库新增资源 **0 字节**（不内置任何 lang）。
  - 运行时缓存：`zh_cn.json` **385 KB**（本环境异常包 562 KB）。
  - SQLite 增量：**1,369 行**（方块 987 + 物品 382），整表 JSON 约 **160 KB**，落库约 200 KB 量级——相对 6,759 行的 mod 物品表约 +20%。
- **一次性成本**：冷启动 4 个请求 / 1.26 MB / **4.4 s**；之后命中缓存 0 s；只想刷新中文时 1 个请求 / 385 KB / **1.2 s**。
- **对 6.9 s 扫描基线的影响**：离线部分实测 **0.11 s**（lang 0.016 + datapack 0.075 + class 常量池 0.024），约 **+1.6%**；即使首次带下载，也只是一次性 +4.4 s，不进每次重建。
- **失败回退**（按顺序）：
  1. 官方 CDN（`launchermeta`/`piston-meta`/`resources.download.minecraft.net`）失败 → BMCLAPI 镜像：`https://bmclapi2.bangbang93.com/assets/<hash前2位>/<hash>` 实测 200、与官方同大小；`https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json` 实测 200。
  2. 仍失败 → 读数据目录下服主放置的 `vanilla/zh_cn-<ver>.json`（与 CFPA zip 手动兜底同一机制）。
  3. 仍失败 → **照常建库，只写英文名**，`zh_source='none'`，在重建回执里明确“原版中文名缺失（下载失败，可手动放置）”。
  4. 服务器安装里找不到 `en_us.json`（非 Forge/被裁剪） → 跳过原版块，回执里给出原因，不影响 mod 物品库。
- **幂等/缓存**：按 `(mc_version, sha1)` 缓存，重建不重复下载；sha1 校验失败丢弃重下一次，再失败走回退。
- **版本一致性保护**：只把 lang 当字典（按本地已有 ID 取键），不拿它的键去生成 ID——这样即使下载到更新/更旧版本的语言文件，也不会污染 ID 集合（本环境的 8,655 条包验证过：键集是超集，覆盖 1,369/1,369）。

### 4.2 兜底：B（完全不联网）

- 原版只建“ID + 英文名”（1,369 行，0.11 s，零网络）。
- 中文名来源只剩两条：服主手动放 `zh_cn.json` 到数据目录（推荐，和 `zh_cn_extra.json` 一样简单），或走 `zh_cn_extra.json` 自己补。
- 查询时中文查不到原版 → 命中英文名/ID 也能返回，并在结果里标注 `"name_zh": null`，由工具文案提示“原版中文名未加载”。

### 4.3 明确不做的事

- 不把 `zh_cn.json` / `en_us.json` / 任何清洗后的常量表提交进 git、打进 wheel、随插件发布。
- 不对外提供 lang 镜像/代理下载地址。
- 不把下载缓存写进仓库目录，只写 `StarTools.get_data_dir()`。

---

## 5. 对 design.md 的具体修改建议（可直接抄）

**5.1 数据来源与合并优先级（design 3.1 节）**：在现有优先级下面补一段（原版命名空间与 CFPA 不冲突，CFPA 没有 `minecraft` 命名空间）：

> 原版（`minecraft:`）单独一条来源链，与模组链互不影响：
> `zh_cn_extra.json`（`minecraft:*` 键） > 官方 `zh_cn.json`（重建时下载或服主放置） > 空。
> 原版不使用 CFPA（CFPA 不含 `assets/minecraft/lang`，实测 1-20 包 608 个命名空间里没有 `minecraft`），也不依赖 mods jar（278 个 jar 里只有 1 个覆盖了 `assets/minecraft/lang/en_us.json`，zh_cn 为 0）。

**5.2 新增「原版数据（kb/vanilla.py）」一节**：

> - **ID + 英文名**：从 `<mc_server_dir>/libraries/net/minecraft/server/*/server-*-extra.jar`（依次回退 `-unpacked.jar`、`server-<ver>.jar` 内嵌的 `META-INF/versions/<ver>/server-<ver>.jar`）读取 `assets/minecraft/lang/en_us.json`（1.20.1 实测 386,499 B / 6,217 条）。
> - **ID 还原**：取 `item.minecraft.<id>` / `block.minecraft.<id>` 且键中恰好两个点的条目，得到候选；再与同一 jar 的 `data/minecraft/**/*.json` 中 `"minecraft:<id>"` 引用、以及 `-srg.jar` 里 `Items.class`/`Blocks.class` 常量池字符串求交，得到 1,369 个（实测精度 100%、召回 97.6%，代价 0.11 s）。
> - **中文名**：`vanilla_zh.json` 按 `block.minecraft.<id>` → `item.minecraft.<id>` 查（索引 1,369/1,369 命中）。语言文件只当字典，**不用它的键生成 ID**，避免版本不一致污染。
> - **kind**：有 `block.minecraft.<id>` 键的标 `block`（987），其余 `item`（382）。
> - **说明**：缺失的 33 个（17 个锻造模板 + 16 个墙旗）在 1.20.1 没有语言键，无名字可查，一期接受；KubeJS 运行时 dump 存在时可覆盖补齐（dump 实测 1,402 个 vanilla ID）。

**5.3 新增「原版中文下载（可选、运行时）」一节**：

> 与 CFPA 下载同一套 HTTP 工具：`version_manifest_v2.json` → 版本 json → `assetIndex` → `objects["minecraft/lang/zh_cn.json"]` → `https://resources.download.minecraft.net/<sha1[:2]>/<sha1>`；sha1 校验；缓存 `data_dir/vanilla/zh_cn-<ver>.json`；失败回退 `https://bmclapi2.bangbang93.com/assets/<sha1[:2]>/<sha1>`，再回退服主手动放置。**不下载 client.jar（23 MB，且里面只有 en_us）**。
> 合规：官方资源只在运行时下载/本地缓存，不随插件分发，不提供镜像；重建回执与 README 注明“原版语言文件来自 Mojang 官方资源，仅本地使用”。

**5.4 配置项（design 第 4 节）**：加一行（其余不变）：

| key | 类型 | 默认 | 说明 |
|---|---|---|---|
| `vanilla_kb_enabled` | bool | true | 是否把 `minecraft:` 原版物品并入知识库（读服务器安装的 en_us，离线） |

（中文是否下载复用现有 `cfpa_auto_download` 的语义即可，或新增 `vanilla_zh_download`，二选一，不要两个开关。）

**5.5 SQLite schema（design 3.3 节）**：不改表结构，只把 `zh_source` 的取值扩为 `extra | cfpa | vanilla | jar | none`，并允许 `name_zh IS NULL`（原版中文未加载时）。

**5.6 指令统计（design 5.1 节）**：重建回执加一行：

> 原版：1,369（方块 987 / 物品 382），中文 1,369（官方 zh_cn，sha1 <前8位>）；英文来自服务器安装 en_us.json。

**5.7 风险（design 第 6 节）**：补一条：

> 风险：Mojang 资产镜像可能返回与版本不符的 lang（本次实测：官方 index 的 1.20.1 zh_cn 含 1.21 物品，8,655 条；真 1.20.1 为 6,215 条）→ 因此只按 ID 取键，不按 lang 生成 ID；下载后校验 1,369 个键的命中率，低于 95% 时告警并退回英文。

**5.8 顺带更正 research/05 第 104-105 行**：

> 原文：“服务端安装里没有 client jar … 必须内置一份原版 1.20.1 zh_cn.json（约 6,000 条常量表）”。
> 更正：服务端安装确实没有 client jar，但 Forge 的 `extra.jar`/`unpacked.jar` 含官方 `en_us.json`（386 KB / 6,217 条），可离线还原 1,369 个原版 ID + 英文名（0.11 s，精度 100%）；中文名只需 385 KB 的 `zh_cn.json`，运行时下载即可，**无需内置常量表**。

---

## 6. 如果一期不做原版：查询工具必须返回什么

现状风险：`search_mc_items("钻石剑")` 返回空数组，LLM 会直接说“游戏里没有这个物品/找不到”，这是**误报**——原版物品一直存在，只是知识库没收录。

要求（按重要性）：

1. **区分“知识库没有”和“游戏里没有”**：返回值里带 `vanilla_enabled: false` / `vanilla_note`，文案明确“原版物品未收录，但可直接用 ID 或中文名调用 give_item”。
2. **告诉 LLM 下一步怎么做**：给出示例（`stone`/石头、`diamond_sword`/钻石剑）和“可以直接把中文名交给 give_item，RCON 由原版解析”。
3. **不要返回空数组**：至少返回一个带说明的对象/提示文本。
4. **不要在文案里说“不存在”**，用“知识库未收录/未启用”。

建议文案（可直接用）：

```json
{
  "items": [],
  "total": 0,
  "vanilla_available": false,
  "note": "知识库未收录原版（minecraft:）物品：原版物品库未启用或构建时未找到服务器安装。原版物品在游戏里是存在的，可以直接把中文名或英文 ID 交给 give_item（例如 stone / diamond_sword），不要回答“没有这个物品”。管理员可运行 mc_kb_rebuild 启用原版收录。"
}
```

若知识库已启用原版、只是这次关键词没命中（例如查“墙旗”这类没有语言键的 33 个），文案改为：

> “知识库里有 1,369 个原版物品/方块，但没匹配到「<kw>」。可能是该 ID 没有官方名称（如锻造模板、墙旗），可以直接用完整 ID 试：`give_item("minecraft:<id>")`。”

---

## 7. 未解决的疑点

1. **本环境 Mojang 资产链返回的 1.20.1 lang 不是真 1.20.1**（8,655 条含 mace/crafter，且 index 缺方块贴图）。真 1.20.1 的 6,215 条/385 KB 是用版本化镜像交叉验证的（`InventivetalentDev/minecraft-assets@1.20.1`）。真实部署里按官方 index 应该拿到 385 KB 那份，但**上线前建议在目标网络实测一次**，并在代码里做第 5.7 条的命中率告警。
2. **Forge 安装布局依赖**：`libraries/net/minecraft/server/*-extra.jar` 是 Forge 安装器产物；纯 vanilla 服务端只有 bundler（内嵌 jar 里有 en_us，本脚本已支持），如果服主删了 `libraries/` 就完全拿不到——需要第 4.1 节的回退 4。
3. **1.20.2+ 的语言键结构变化**（如 `item.minecraft.*` 的拆分）没有验证；一期只声明 1.20.1。
4. **33 个无语言键的 ID**（17 锻造模板 + 16 墙旗）要靠运行时 dump 才能补，是否值得做取决于产品判断；它们本来也没有中文名可搜。
5. **服主自备 `.minecraft/assets` 路径未实测**（本机没有 `~/.minecraft`）；只验证了“client.jar 不含 zh_cn”这个关键结论。
6. **法务灰区**：运行时下载官方 lang 是否被 Mojang 视为“再分发”——我的判断是不构成（与启动器行为一致、只落本地），但这是解释而非明文许可，若要绝对稳妥就走方案 B（完全不下载，只读服务器本地 en_us + 服主自备中文）。

---

## 附：复现用脚本与关键命令

| 脚本 | 用途 |
|---|---|
| `/tmp/vanilla/probe_jars.py` | 列出 5 个 server jar 的 assets/data/lang 分布 |
| `/tmp/vanilla/analyze.py` | 用 minecraft-data 做初版精度/召回对照 |
| `/tmp/vanilla/final_pipeline.py` | datapack + class 常量池交集、分类、覆盖率 |
| `/tmp/vanilla/vanilla_pipeline.py` | **可直接移植的离线管道原型**：定位 jar → 读 en_us → 候选 → 交叉验证 → 计时 |
| `/tmp/vanilla/dl_lang.py` | 官方链路下载 zh_cn（冷/热/单文件三种计时 + sha1 校验） |
| `/tmp/vanilla/gt_check.py` | 与 KubeJS 运行时 dump（1,402 个真实 ID）对照精度/召回 |
| `/tmp/vanilla/final_numbers.py` | 生成 1,369 行 KB 记录、统计中文覆盖与体积 |
| `/tmp/vanilla/final_checks.py` | CFPA 1.12.2 占位、1-20 包命名空间、mods lang 扫描 |

关键命令（节选，均已实测）：

```bash
# 1) 服务端自带 en_us 与 ID 还原
python3 /tmp/vanilla/vanilla_pipeline.py

# 2) 官方 zh_cn 单文件下载（冷启动 4.41s / 1.26MB；单文件 1.21s / 562KB）
python3 /tmp/vanilla/dl_lang.py

# 3) 与真实注册表对照
python3 /tmp/vanilla/gt_check.py

# 4) BMCLAPI 镜像可用性
curl -sSL -o /dev/null -w '%{http_code} %{size_download}\n' \
  https://bmclapi2.bangbang93.com/assets/56/561ed7800004b882b8eeb032ffbe2bf03895bb44
```
