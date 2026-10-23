# 模组物品认知：修 minecraft: 硬编码 + 物品/翻译知识库

## Goal

让 AI 认识 Forge 整合包里的模组物品：修复 give_item / clear_inventory / summon_entity / fill_blocks 四处无条件补 minecraft: 前缀导致模组物品必失败的 bug；构建物品/翻译知识库（离线扫 jar 兜底 + KubeJS 运行时 dump 增强，CFPA 汉化包 + 服主自定义补译），并提供免权限的查询类 LLM 工具。配方查询为二期范围。

## 背景

- 插件靠 RCON 发原版命令，工具以 @filter.llm_tool 装饰器 + docstring Args: 注册，现有 30 个工具。
- 实测两个 1.20.1 Forge 服（Farming 278 mods / zyjd 228 mods）；研究报告与实测数字见 research/ 目录（01/02/03/05/06）。
- 需求边界已与用户逐条确认（2026-10-21 grill 共 9 项决策，见下「已确认决策」）。

## 已确认决策

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 数据来源 | 两者结合：默认离线扫 jar；检测到 KubeJS 时支持运行时 dump 增强 |
| 2 | 构建时机 | 服主手动触发指令重建，不做启动时自动扫描 |
| 3 | 中文来源优先级 | 服主自定义 zh_cn_extra.json > 整合包 kubejs 资源包（kubejs/assets）> CFPA 汉化包 > 模组 jar 自带 |
| 4 | CFPA 包获取 | 按服务器 MC 版本自动下载（GitHub Releases，失败回退 BMCLAPI 镜像）；支持服主手动放 zip 兜底 |
| 5 | 许可证 | 接受 CC BY-NC-SA 4.0：运行时下载不随插件分发 + README/指令输出署名 |
| 6 | 工具权限 | 查询类 LLM 工具免权限（只读） |
| 7 | 一期范围 | 修 4 处硬编码 bug（含 fill_blocks）+ 物品/翻译知识库 + 查询工具；配方（先「能查」）二期再做 |
| 8 | 原版物品名来源 | 不内置原版常量表。ID + 英文取服务端 Forge 自带的官方 en_us（离线，实测 1,369 条）；中文按服务器版本从官方下载 zh_cn（默认开，缓存/BMCLAPI/手放/客户端回退），lang 只当字典、绝不用于生成 ID；不下载 client.jar，方块可 give 用 loot 表近似并标注推测 |

## Requirements

1. **修 bug**：tools/game_tools.py 的 give_item、clear_inventory 与 tools/world_tools.py 的 summon_entity、fill_blocks（交接文档记录 3 处，设计阶段复核发现 fill_blocks 同样存在），传入已带命名空间的 ID（modid:path）时不得再强制补 minecraft: 前缀；传原版短名时保持原行为（补 minecraft:），不回归；clear_inventory 不传物品时仍清空整个背包。这 4 个工具的 docstring 需补一句"也可传模组物品完整 ID，如 create:brass_ingot"，让模型知道可以传命名空间 ID。（实现注：fill_blocks 目前只是脚本层函数、未暴露为 LLM 工具；模型侧填方块走 execute_command 的 fill，查询文案已按实际可用工具校正。）
2. **物品/翻译知识库**（SQLite，存于插件数据目录 StarTools.get_data_dir）：
   - 默认离线扫描服务器 mods/*.jar，提取物品 ID 与自带语言文件（中文/英文键名）；
   - 检测到 KubeJS 时支持可选的运行时 dump 增强（丢入 server_scripts 的 dump 脚本原型已存在：research/02 与 /home/guigui/mc/.research/runtime-dump/）；
   - 中文补译：自动下载 CFPA 汉化包（按 MC 版本，GitHub Releases 优先、BMCLAPI 镜像回退），或读取服主手动放置的 zip；服主自定义补译文件 zh_cn_extra.json 优先级最高；
   - 原版（minecraft: 命名空间）名称：不内置常量表。ID 与英文名取服务端 Forge 自带的官方 en_us（`libraries/.../server-*-extra.jar`，离线、零网络）；中文按服务器版本从官方下载 `zh_cn.json`（约 1.3 MB / 4 个请求，默认开，缓存 + BMCLAPI + 服主手放 + 客户端 assets 回退）；都拿不到时降级为"原版只落英文/ID"；不下载 client.jar，方块「可 give」用 loot 表近似并标注推测；
   - 重建由服主通过插件指令手动触发，完成后报告条目统计。
3. **查询类 LLM 工具（免权限、只读）**：支持用中文名/英文名/物品 ID 模糊查询，返回 modid:itemid、中英文名称与所属模组；查不到时明确说明"知识库未收录"，并提示原版物品可直接用 ID，不得让模型把"库里没有"当成"物品不存在"。
4. **合规**：CFPA 数据仅在重建时运行时下载，不随插件仓库分发；README 与重建指令输出中标注来源与 CC BY-NC-SA 4.0。

## 非目标（二期）

- 配方知识库与配方查询（「能查」级别：按产物查配方、按材料反查用途）；配方「理解」（材料是否足够、步骤模拟）更后。
- 知识库自动更新调度；预构建库随插件分发。

## Constraints

- 纯 Python、优先标准库（物品扫描器原型 716 行纯标准库，Farming 实测 6.9s / 171MB：/home/guigui/mc/.research/prototype/scan_items.py）。
- 目标环境 MC 1.20.1 Forge 为主，尽量版本通用（1.12.2 的 .lang 格式差异见 research/06 第 4 条，一期可只支持 1.13+ JSON 格式，超出则明确报错）。
- 不拖慢插件启动（手动触发重建）；不修改服务器 mods 目录任何文件。
- 复用现有 llm_tool 注册方式与 _check_permission 权限体系（查询工具免权限）。

## Acceptance Criteria

- [ ] give_item / clear_inventory / summon_entity / fill_blocks 传入 "modid:item" 形式 ID 时按原样执行；传入原版短名（如 stone）行为与修复前一致。
- [ ] 服主可通过插件指令手动重建知识库，指令完成后返回物品/翻译条目统计；重复重建幂等。
- [ ] 中文覆盖率达标（门槛依据 research/08 实测）：Farming 全量 **≥55%**、give 可用子集 **≥52%**；zyjd 全量 **≥67%**、give **≥68%**；接入 CFPA 后全量覆盖率相对"仅 jar 自带翻译"至少提升 **3 个百分点**（实测 Farming +7.8pp、zyjd +4.6pp）。
- [ ] 知识库覆盖 mods 目录扫描到的模组物品，并包含整合包 `kubejs/assets/*/lang` 资源包层（Farming 实测该层贡献 10,224 条 id，不扫则覆盖率掉到 48.1%）。
- [ ] CFPA 下载失败（断网/源不可用）时给出明确错误提示，且服主手动放置 zip 后可完成构建。
- [ ] 新增查询工具可用中文/英文/ID 模糊查到模组物品（对 Farming / zyjd 两服实际 mods 抽查若干模组物品验证），非管理员可用。
- [ ] 原版物品可查到完整 ID 与中英文名（1.20.1 实测 1,369 条 item/block：987 方块 + 382 物品，外加 126 实体名；中文命中 100%）；中文按服务器版本自动下载并缓存，断网且无本地文件时降级为只建英文，查询不报错并返回"原版物品可直接用 ID"提示。
- [ ] 方块「可 give」判定：有客户端时精确（models/item）；无客户端时用服务端 loot 表近似并在查询里标注「推测」，不得把推测值当确定值。
- [ ] 不下载 client.jar（23 MB）；原版建库不因缺少客户端而失败。
- [ ] 原版 id 全集取服务端 en_us 的三段键（与 data/minecraft 引用交叉），中文表只当字典——不得把 1.21 之类的跨版本条目（如 minecraft:mace）写进 1.20.1 服务器。
- [ ] 现有 30 个工具的 RCON 命令拼装与权限行为不回归。

## 关联

- GitHub issue（fork）：https://github.com/fanjinchi/astrbot_plugin_mc_manager/issues/2（二期：#1）

## Notes

- research/ 目录：01 静态提取、02 运行时 dump、03 配方与 JEI、05 汇总、06 CFPA 汉化包调研。
- 关键陷阱：/forge dump 不存在于 Forge 47.4.0、/ct dump 需在线玩家、/jei 服务端无命令、KubeJS export 不导配方、Ingredient.getItems() 在 KubeJS 桥接下全空（必须用 Ingredient.toJson()）、Farming/hotai/ 是 class 补丁非翻译——详见 research/05 第 6 节。
- 本任务为复杂任务：需补 design.md + implement.md 后再 task.py start。
