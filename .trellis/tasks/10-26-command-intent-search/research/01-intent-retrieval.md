# 中文意图下的模组命令检索调研

## 结论

- 模组命令没有统一、完整的中英文功能说明来源；模组 lang 中的 `command*` 主要是执行反馈，不是命令用途。
- 对调用方 LLM 而言，权威英文说明通常足以支持中文意图理解，不要求先翻译成中文；但只有 usage、没有说明时，两种语言都可能缺语义。
- 最小夹具显示，当前首要断点是**候选召回和整串匹配**，不是“缺少自动生成中文”。英文单 token 能召回目标后，usage 往往已足够选择命令。
- 因此当前决策是英文调用引导 + 无序 token AND；自动中文、文档抓取和 rerank 只作为真实模型验收失败后的重新评审方向。

## 证据边界

- 调研和原型只读检查本机 CTI0.46（1.19.2）与 Farming（1.20.1）的实际 mod JAR，并查询公开官方资料；未连接服务器、未执行 MC 命令。
- 调研时两个实例均没有真实 `commands.json`：CTI 的 `runtime_dump/` 只有 item/block/entity/fluid，Farming 没有该目录。样本不是全量 dispatcher 快照。
- 原型使用 19 个根、49 条 usage 的临时夹具，不是生产数据；当时路径 `/tmp/mckb_probe/`，不作为后续验收依赖。
- 被测 `kb/commands.py` SHA-256：`1926a10434f196f2a1da2be41b7cb799745f6190fb06a76312dd7c1dbbd80a79`；夹具 SHA-256：`644f5858e569c2e9016f543c30953c32edd3ce5f865142dc9363281754e47219`。
- 候选选择不是盲测，不能据此证明任意部署模型在真实 200+ 根命令规模下能稳定选择。

## 中英文资料是否真实存在

| 来源 | 实测结论 |
|---|---|
| 原版中文说明 | 中文 Minecraft Wiki 完整；插件 `assets/vanilla_commands.json` 内置 74 条人工中文 desc |
| 模组 zh_cn/en_us lang | 两实例扫描 249/278 个 JAR，约 1/6 有命令类 key；这些 key 是反馈/错误文本，不是功能说明，且中文覆盖参差 |
| 模组官方英文文档 | 部分存在且质量较高；Waystones、FTB Quests 有逐命令 Description，其他模组可能只有零散 wiki 或完全没有 |
| 中文社区资料 | MC 百科等部分模组有“指令”分类，但覆盖和内容质量未得到普遍验证，不是统一机器来源 |
| dispatcher usage | 两个生产者均可提供真实命令路径；不提供统一功能描述，也不保证 RCON 可执行 |

代表性本地样本：

| 根命令 | 实际证据 | 官方英文命令说明 |
|---|---|---|
| `wine` | Vinery JAR：`wine age <years>`、`wine info`；执行体要求玩家 | 未找到；usage 可提示 age，但 RCON 执行限制是独立问题 |
| `mek` | Mekanism JAR：`radiation removeAll/add/get/heal/reduce/...` | wiki 零散提及；语法仍以实际 JAR/dispatcher 为准 |
| `ae2` | AE2 JAR：`channelmode` 及 infinite/default/x2/x3/x4 | 未找到完整命令参考；x2/x3/x4 语义不能由名称完全保证 |
| `botania-skyblock` | Botania JAR：island/spawn/visit/regen-island 等 | 未找到完整命令说明 |
| `waystones` | Farming 1.20.1 JAR 有命令；CTI 1.19.2 对应 JAR 未找到命令注册 | 官方有完整命令表，可区分 `list` 与 `list all` 的语义 |
| `ftbquests` | FTB Quests JAR：editing_mode 等，权限节点可见 | 官方有完整命令 Description |

结论不是“英文说明覆盖所有模组”，而是：**有英文说明时 LLM 可以直接利用；没有时自动生成中文也只是把猜测固化，并未增加事实依据。**

## 当前链路为何断

- `main.py` 的 `search_mc_commands(keyword)` 由调用方 LLM 自己决定关键词。
- `kb/commands.py` 对 name/usage/desc/redirect 做小写整串包含匹配。
- 内置 vanilla 有中文 desc；运行时模组条目没有可靠中文 desc。中文关键词直接搜英文 usage 通常不能召回。
- 因而“LLM 能理解英文”与“英文候选能进入 LLM 视野”是两个问题；本任务只解决后者及候选 usage 展示，不新建翻译数据。

## 最小原型结果

### 五条代表意图

| 中文意图 | 中文直搜 | 英文 token 检索 | 英文说明的作用 | 执行边界 |
|---|---|---|---|---|
| 把酒陈酿到 10 年 | 陈酿/葡萄酒/酒均未命中 | `wine` 命中 `wine age <years>` / `wine info` | 定位不需要 | 字节码显示玩家限定；检索成功不代表 RCON 可执行 |
| 给 Steve 开启任务编辑模式 | 任务编辑/任务未命中 | `editing` 等命中 `ftbquests editing_mode...` | 官方说明只做事后确认 | 未实际执行；玩家在线和权限另属执行层 |
| 看看老王激活了哪些传送石碑 | 传送石碑未命中；“传送”只命中 vanilla 噪声 | `waystones` 命中目标根和 list usage | 需要文档区分“已放置”与“已放置或激活” | 版本不同命令可能不存在；未实际执行 |
| 清掉全服辐射 | 辐射未命中 | `radiation` 命中 `mek radiation removeAll` | 定位不需要 | 未执行该有状态命令 |
| 把 AE2 频道模式换一下 | 频道模式/频道未命中 | `channelmode` 命中根及合法模式值 | 定位不需要；倍数含义可能需文档 | 用户缺目标值，必须反问而非编造 |

英文 token 对这五条均使目标根和目标 usage 出现在工具输出中；这证明**信息可以被现有工具返回**，不证明生产模型一定稳定生成这些 token。

### 匹配器

- 多词整串查询 `quest editing`、`waystone list`、`channel mode`、`remove radiation` 等因词序、空格或单复数差异漏检；只有词序恰好连续的 `radiation removeAll` 等能命中。
- 临时 token-AND 原型在 8 个扩展查询中挽回 6 个；`clear radiation` 仍需同义词，`传送石碑` 仍需跨语言，均不在本期匹配承诺内。
- token 采用子串匹配有现实依据：`quest` 应能命中 `ftbquests`，`waystone` 应能命中 `waystones`，`channel` + `mode` 应能命中 `channelmode`。这也意味着 `age` 等模糊词会有子串噪声，需要保留精确根名优先级并鼓励具体查询。
- 只搜 `mek` 时，目标 `removeAll` 曾被单根 8 条上限折叠。保留上限是为了避免 `/execute` 等淹没上下文；正确解法是细化子命令词并让完整命中的 usage 优先，而非无差别展开整棵树。
- 负对照中，删除正确根后精确 token 通常安全无结果；`mode`、“传送”等模糊词会返回看似相关但错误的 vanilla/其他根，不能把“有结果”当“命中目标”。

## 当前决策与后续闸门

1. 工具说明和无结果提示引导调用方把中文意图提炼为简短英文概念词，必要时换更短词或英文同义表达。
2. 查询支持无序 token AND，兼容空格、下划线、连字符；不做自动翻译、同义词库、词干、拼写纠错、拼音或语义打分。
3. 单 token、原版中文 desc、redirect、坏快照和 producer 提示保持回归；单根 8 条上限不变。
4. 复用子任务一的真实快照，在实际 AstrBot 调用链验证 5 条代表意图，必须 5/5 召回正确根与目标 usage；只检索，不执行 MC 命令。
5. 任一真实用例失败则返回规划分析，由用户决定是否评估 rerank、英文资料增强或自动中文层，不在实施中自行扩 scope。

## 尚未证明

- 真实全量快照的规模、排序和 usage 截断表现。
- 部署模型是否稳定翻译和选择；本实验不是盲测，也不是生产模型端到端结果。
- 弱模型、不透明根名和无资料长尾是否最终需要自动中文层。
- 任何命令的实际执行成功率；本任务只验收检索。

## Sources

- [FTB Quests — Commands](https://docs.feed-the-beast.com/mod-docs/mods/suite/Quests/Developer/Commands)
- [Waystones — Commands](https://mods.twelveiterations.com/minecraft/waystones/guides/commands/)
- [Mekanism Wiki — Radiation](https://wiki.aidancbrady.com/wiki/Radiation)
- [中文 Minecraft Wiki — 命令](https://zh.minecraft.wiki/w/%E5%91%BD%E4%BB%A4)
- [MC百科 — 应用能源2](https://www.mcmod.cn/class/260.html)
