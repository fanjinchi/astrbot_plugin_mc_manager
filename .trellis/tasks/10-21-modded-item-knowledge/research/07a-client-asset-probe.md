# 原版（vanilla）物品名现场提取实测 · 客户端资源路线

调研时间：2026-10-21 主会话实测
样本：用户提供的农场物语客户端（PCL 版本隔离）`/home/guigui/mc/nongchangwuyu`
目标服：`/home/guigui/mc/Farming`（MC 1.20.1 Forge 47.4.20，278 mods）

## 结论（一句话）

**不需要内置任何常量表**：从本机客户端安装现场读两处即可拿到全部原版 id 与中英文名——中文在 `assets/objects`（按资源索引取），英文在客户端版本 jar 的 `assets/minecraft/lang/en_us.json`。1.20.1 实测拿到 **1,530 条原版 id、中文缺失 0 条**。全程离线、不随插件分发、天然跟随版本。

## 提取位置（实测）

客户端目录结构（PCL 版本隔离）：

    /home/guigui/mc/nongchangwuyu/.minecraft/
      ├── assets/indexes/5.json          # 1.20.1 资源索引（sha1 与 Mojang 官方一致）
      ├── assets/objects/xx/<hash>       # 内容寻址资源，含 minecraft/lang/zh_cn.json
      └── versions/FarmingTales_ForgeⅡ v1.5.2fix2/
            ├── <pack>.jar               # 21MB 客户端 jar，含 assets/minecraft/lang/en_us.json + version.json
            └── <pack>.json              # clientVersion 1.20.1，assetIndex.id = 5

关键实测：

| 事实 | 证据 |
|---|---|
| 版本 jar 内 `version.json` 的 id = `1.20.1` | 读 jar 内 `version.json` |
| 版本 jar 内有 `assets/minecraft/lang/en_us.json`，**没有** zh_cn | `zipfile.namelist()` |
| 中文在 `assets/objects/3c/3c1a6e6c…`（555,676 字节） | index 5 → hash → 文件存在 |
| 本地 index 5 与官方 sha1 `c8035a2d…` 完全一致 | `sha1sum` + curl 官方 index 对比 |

## 中英文表的版本一致性（重要）

| 数据 | 条目 | 三段 id 数 | 版本一致性 |
|---|---|---|---|
| `en_us.json`（jar 内） | 6,217 keys | item 415 / block 989 / entity 126 | **严格 1.20.1**：`mace`/`wolf_armor`/`copper_bulb`/`acacia_shelf` 全部不存在 |
| `zh_cn.json`（assets） | 8,562 keys | item/block/entity 共 2,996 | **超集**：含 1.21 的 `item.minecraft.mace`=`重锤`、`wolf_armor`、`trial_key`、`banner.flow.*` 等 580 条 |

→ 所以 **id 全集必须以 en_us 为准，zh_cn 只当名字字典并对 id 求交**。直接用 zh 建库会往 1.20.1 服务器里塞 1.21 的 id（give 必失败）。

## 可 give 判定（has_item）

客户端 jar 里有 `assets/minecraft/models/item/<path>.json`，这正是"方块有没有物品形式"的信号：

- item 键（415）→ `has_item=1`
- block 键（989）：其中 **856 个有物品模型**（stone / oak_log 有；acacia_wall_sign / attached_melon_stem / banner.base 没有）
- entity 键（126）→ 供 summon_entity 用

## 实测汇总（1.20.1）

- 原版 id 总数：**1,530**（item 415 + block 989 + entity 126）
- 可 give：**1,271**（415 item + 856 有物品模型的 block）
- 中文缺失：**0**（1,530 条全部能在 zh_cn 里查到；`diamond_sword`=钻石剑、`stone`=石头、`iron_ingot`=铁锭、`zombie`=僵尸）
- 提取成本：读 1 个 index JSON（413KB）+ 1 个 object（555KB）+ 1 个 jar 内的 1 个 entry（热读，不必解整包），实测 < 1 秒

## 许可

插件只在运行时读用户本机的客户端安装，**不下载、不打包、不随插件分发任何 Minecraft 资产**；用户本来就有这份客户端。比"内置常量表"和"运行时从 Mojang 下载"都干净。

## 建议的配置与降级

- 新配置 `mc_client_dir`（可选）：指向客户端 `.minecraft`（或含 `versions/`、`assets/` 的目录）。
- 提取顺序：`versions/**/*.jar` 中找含 `assets/minecraft/lang/en_us.json` 的 jar（读 `version.json` 校验）→ 从版本 json 的 `assetIndex.id` 定位 index → 取 `minecraft/lang/zh_cn.json` object。
- 降级：只有 zh（无 jar）→ 用 zh 全集并在回执标注"可能含与服务器版本不符的条目"；两者都没有 → 原版不建库，查询命中时走"原版物品可直接用 ID"提示。
- 版本不匹配（客户端 jar 的 version.json ≠ 配置/探测的 mc_version）：给警告但不阻断（整合包客户端升级滞后于服务端是常态）。

## 未解决 / 待确认

1. 只有 asset objects、没有客户端 jar 的安装（例如用户只下过资源），拿不到英文名 —— 是否接受"原版只有中文名"？
2. 客户端 jar 在部分启动器里是 `versions/<ver>/<ver>.jar`，在 PCL 整合包里是 `<pack>.jar`，需按"扫所有 jar 找 en_us"而不是按文件名猜。
3. 原版 `has_item` 依赖 `models/item`；若某版本把模型挪进 assets objects（目前看没有），需要补一条从 index 取模型的路径。

## 与 research/07 的关系（合并说明）

07 是主结论：服务端 Forge 的 `server-<ver>-extra.jar` 自带官方 `en_us.json`，**英文与 ID 全集不需要客户端**（1,369 条，0.11 s）。本文回答的是「中文从哪来」：

- 中文不在客户端 jar 里，而在 `assets/objects`（按资源索引取）——所以 `mc_client_dir` 的价值是**离线拿中文**与**判定方块有无物品形式**（`models/item`），不是拿 ID。
- 本文的 1,530 条包含 entity 126 与未与注册表交叉的候选键；按 07 的交叉验证口径，item/block 部分为 1,369 条。两者不矛盾：实现以 07 的口径为准，entity 为 best-effort。
- 两份实测独立确认了同一个坑：拿到的 zh_cn 是「新版」超集（含 mace 等 1.21 内容），只能当字典、不能生成 ID。

## 复现数字与 08 的关系

08 的 `minecraft` 行为：Farming 1,460 条 / 中文 164（11.2%）、zyjd 1,090 条 / 中文 3（0.3%）——这是**纯静态扫描**（只认被 mod 引用的 minecraft: id）的现状；接入 07 方案后原版为 1,369 条 item/block + 126 实体名，中文命中 100%。

## 补充实测：没有客户端时，方块「可 give」的服务端近似

服务端 `server-1.20.1-*-extra.jar` 里有 `data/minecraft/loot_tables/blocks/`（925 个文件）。以客户端的 `models/item` 为基准对比 989 个 block 键：

| 判定方式 | TP | FP | FN | TN | 精确率 | 召回率 |
|---|---|---|---|---|---|---|
| loot 表存在 ⇒ 可 give | 845 | 80 | 11 | 53 | **91.4%** | **98.7%** |

- 误判（有战利品表但无物品形式）：`beetroots`、`attached_melon_stem`、`black_candle_cake` 等植物/装饰方块；
- 漏判（无战利品表但有物品）：`bedrock`、`command_block`、`barrier` 等不破坏方块。

结论：不配客户端也能给出可用的近似值，代价是少量误判（LLM 试一次 give 失败即回退）。因此**不下载 23 MB 的 client.jar**；有 `mc_client_dir` 时用 models 精确判定，没有时用 loot 近似并在查询里标「推测」。
