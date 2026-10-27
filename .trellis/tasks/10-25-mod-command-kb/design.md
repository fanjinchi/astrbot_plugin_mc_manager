# 模组命令知识库技术设计

## 1. 总体路径

- 主路径：复用 `RuntimeDumpRunner` 和 `assets/runtime_dump.js`，从服务器活动 dispatcher 导出结构化 usage。
- 回退路径：无 KubeJS 时，通过 RCON 两阶段 `help` 采集同一 dispatcher 对 RCON source 可见的根命令与一级子命令 usage（HelpCommand 只提供 smart usage，深分支为压缩语法）。根级 help 用于发现、显式 redirect 和首尾根集合检查；普通 usage 来自 targeted 正向一级证据，targeted 空响应或根级 `/foo` 不回填普通纯根。
- 两条路径只负责生产同一种命令快照；`search_mc_commands` 只消费已发布快照，不在查询或 `execute_command` 前实时扫描。
- 子任务顺序：`10-25-kubejs-command-dump` 先建立 schema、发布和查询；`10-25-rcon-help-command-fallback` 与 `10-26-command-intent-search` 均在其后复用这些契约，分别承担 fallback 生产者和英文意图检索增强。

## 2. 共享快照契约

权威文件名统一为 `runtime_dump/commands.json`，采用扁平 usage 条目，而不是按根命令嵌套：

```json
{
  "kind": "commands",
  "schema_version": 1,
  "producer": "kubejs",
  "count": 2,
  "entries": [
    {"name": "wine", "syntax": "wine age <years>", "source": "unknown", "level": null},
    {"name": "wine", "syntax": "wine info", "source": "unknown", "level": null}
  ]
}
```

- `name` 是 dispatcher 根 literal；`syntax` 不带前导 `/`：`producer=kubejs` 时是当前 dispatcher 已注册的完整 usage 路径，`producer=rcon` 时是 help smart usage（含压缩记号，不保证可执行）。KubeJS 路径也不代表当前 RCON/玩家必然可执行，实际执行仍受 `requires`、source 类型和执行体内部玩家检查限制。
- `count` 是 entries 数（usage/redirect 行数），不是根命令数。
- `source` 无法可靠确定时固定为 `unknown`；`level` 无法确定时为 `null`。`desc` 可缺省，不生成模组中文描述或模组功能文档。
- argument 只承诺 `<name>` 形式；不声称可选性、类型、范围、suggestions 或执行体内部的玩家限制。
- redirect 单独表示，不伪装为可执行语法。例如 `alias -> target` 归一为 `{"name":"alias","syntax":"alias","redirect":"target"}`；P0 实测 root target 也是名字形式（如 `execute as <targets> -> execute` 的 `redirect="execute"`），`...` 只作 usage 尾部压缩占位。裸 `->` 若保留仅作额外容错/合成形态并归一为 `redirect="..."`，不得当作本次真实输出。同一节点另有可执行路径时保留其普通 usage 行。
- 发布时按 `name + syntax + redirect` 去重并稳定排序；`syntax == name` 对 KubeJS 是合法纯根 usage，不得全局过滤。RCON 生产者没有裸根 `executes` 正向证据时不得生成普通 `syntax == name`，但显式 redirect 可按别名契约保留；空快照、坏 schema、缺失必要字段或 count 不一致均拒绝发布。
- `producer` 区分来源：`kubejs` 用 `getAllUsage(..., false)` 导出当前 dispatcher 已注册的完整 usage 路径，不执行 `requires` 可见性过滤；`rcon` 用 HelpCommand smart usage（根 + 一级子命令可还原，更深分支含 `(a|b)` / `[x]` / `-> t` / `...` 压缩记号）。查询必须按 `producer` 标注语法可信度，`rcon` 快照不得冒充 KubeJS 的完整已注册路径，KubeJS 结果也不得暗示当前调用者必然可执行。
- 命令快照不做进程级缓存，或重建后立即失效：AstrBot 是长驻进程，`/mc_kb_dump` 后不重启也要能查到新命令；`_vanilla_cache` 那种模块级缓存只适用于随插件分发的固定数据。

### 文件位置与发布

| 场景 | 原始产物 | 查询读取的已发布快照 |
|---|---|---|
| 同机 KubeJS | `<mc_server_dir>/runtime_dump/commands.json` | `<plugin_data>/runtime_dump/commands.json` |
| 同机 RCON fallback | 内存中采集结果（根 + 一级子命令 smart usage） | 同一发布路径，由共享发布函数原子写入 |
| 跨机复制 | 服务器上的 `commands.json` | 复制到插件数据目录对应路径后可直接查询命令；不迁移完整物品知识库 |

- KubeJS 导入先完整读取和校验原始文件，再以同目录临时文件 + `os.replace` 原子替换已发布快照；导入失败保留旧快照。
- RCON 只有全量采集、末次根集合检查和解析成功后才调用同一发布函数。EOF、截断 length/body、错/未知 id、B 缺失/尾随、超时、片数/字节超限、解析失败或可发现的根集合不一致均不得发布部分结果；空 entries 同样拒绝。
- RCON 长响应使用独立低层 socket，但整次扫描持有现有 `_send_lock`，与普通命令/dump 形成同一互斥边界。每个 A=`help`/`help <root>` 必须先收到 `id=A` 首包（合法空包也算），再发送短随机未知 literal B；继续收 A，以 `id=B` 完成，忽略 B 的本地化文本。禁止立即连写 A+B，idle-drain 不能作为完成依据。
- 初始根 help + N 个 targeted + 末次根 help，每次各有一个 B，总计 `2(N+2)=2N+4` 个 RCON 请求。首尾检查只能发现根集合变化及可发现结构异常，不能排除同根集合下 reload；RCON 也无片序号/总长度，不能承诺检测中间内容片被删除但仍收到合法 B 的任意删片。
- 跨机复制 `commands.json` 只承诺命令查询；完整物品迁移沿用现有流程，不在本期新增，物品 builder 仍要求有效的 `mc_server_dir` 和 `mods/`。
- 查询不直接读取服务器原始文件。兼容现有 `commands.jsonl`：仅在 canonical JSON 不存在时读取，生产者不再写 JSONL。
- 原物品 builder 明确忽略 `commands.json/jsonl`，不把命令计入物品 dump 文件数，也不因此改变 `kubejs_hint`。

## 3. 生产者优先级

优先级由显式入口决定，不增加后台调度或时间戳猜测：

1. `/mc_kb_dump` 是 KubeJS 主路径，成功后发布 KubeJS 快照。
2. RCON fallback 的管理员入口由子任务二实现，仅在没有 KubeJS 环境时提供；显式采集成功后可替换当前快照。
3. KubeJS 已安装但一次导出失败时，不自动降级为全量 RCON 扫描；保留旧缓存并报告失败。
4. 任一生产者失败都不得覆盖已有有效快照；不做“旧时间戳一定更新”或跨服务器来源的隐式判断。

## 4. 查询合并与输出

`kb/commands.py` 继续同时承担命令快照读取和查询，避免为本期再拆存储包。

- 内置 vanilla 清单与运行时 entries 按 `name` 合并为一个逻辑结果；同一根的多条 usage 组成有序去重列表，`limit` 限制根命令结果数而不是 usage 行数。
- 纯内置 vanilla 条目保留现有 `source/level` 显示；运行时同根存在时，以真实 usage 为语法来源，只继承内置条目的 `desc/cat`，`level` 显示未知、`source=unknown`，不把内置默认权限或来源当作当前服务器的运行时验证结果，同时避免 `/forge` 等同名重复。RCON 同根只合并其有正向证据的 usage/redirect，不用根级 help 或内置语法补造运行时纯根；KubeJS 纯根条目保持原行为。
- 新根没有内置元数据时显示 `source=unknown`、权限未知和占位描述「运行时命令」，不显示 `None`。
- 搜索范围包括根名、内置描述和完整 usage。关键词只命中 usage 时优先展示匹配分支；单根最多展示 8 条 usage，超出时报告总数并提示细化关键词，避免 `/execute` 淹没上下文。
- redirect 只作为别名/目标提示展示，不列为可直接拼装的完整命令。
- 无运行时快照时保持当前 vanilla 查询行为；损坏快照返回明确警告，不能把错误文本当命令数据。
- `producer="rcon"` 的快照在结果里显示「语法来自 RCON help：一级子命令可还原，深分支为压缩语法，纯根命令可能未收录」的降级提示；targeted 空响应不等于裸根不可执行。`producer="kubejs"` 不显示该深分支/纯根降级提示，但含 KubeJS 运行时结果时统一显示一次「语法为当前 dispatcher 已注册路径，实际执行受权限与 source 限制」的能力边界说明。

- `10-26-command-intent-search` 不改快照 schema 或生产者，只调整工具调用说明与查询匹配：调用方先把中文意图提炼为英文概念词，查询按无序 token AND 匹配并兼容空格/`_`/`-`；保留单根 8 条 usage 上限和原版中文 desc 搜索，不引入自动中文或语义层。

## 5. 重建接线与故障隔离

- `KnowledgeBase.rebuild()` 在物品重建前尝试导入可用命令快照；命令导入失败只追加警告，不阻断物品重建。
- 物品重建失败也不回滚已成功的命令快照；两类派生缓存相互独立。
- `RuntimeDumpRunner` 的既有 rebuild 回调因此可同时完成命令导入；跨机仅复制命令数据目录快照时无需物品库可用，但这不代表完整物品知识库迁移。
- `RuntimeDumpRunner` DONE counts 和 `MANUAL_FALLBACK` 增加 commands 信息；失败类别沿用 `failed` 和旧缓存提示。
- `search_mc_commands` 仍是只读、免权限 LLM 工具，不新增参数语义或模组功能描述。

## 6. 子任务边界

### 子任务一：KubeJS

负责共享 schema、校验/原子发布、查询聚合、`KnowledgeBase.rebuild` 接线、KubeJS 导出、文档与双版本实测。RCON 只使用现有可靠单命令通道触发 `/reload` 和 `/researchdump`，不在此阶段读取长 help。

### 子任务二：RCON fallback

负责 RCON 多包完整接收、request id 隔离、共享 `_send_lock`、A 首包后 B 的受控状态机、help 能力探测、两阶段采集与末次根集合检查、smart usage 解析、纯根/空响应边界、`2N+4` 资源预算和 `/mc_kb_rcon_scan`。必须复用子任务一的发布函数与查询契约，不建立第二套 JSONL 消费链；快照标记 `producer="rcon"`，查询显示深分支压缩和纯根可能未收录。启动前必须先补 design.md / implement.md，并完成双版本隔离副本的 A/B、多包、空包、共享锁与后续命令隔离实测。

### 子任务三：英文意图检索

负责 `search_mc_commands` 的英文概念词调用引导、无序 token AND、多空格/下划线/连字符兼容、相关 usage 优先展示和离线回归。必须复用子任务一的真实快照，并在实际 AstrBot 调用链完成 5 条中文意图的 5/5 召回验收；不执行 MC 命令，不改 schema，不新增自动中文、文档抓取、rerank 或语义层。

## 7. 回滚与兼容

- 新 canonical 文件可整体删除；删除后退回内置 vanilla + 可选旧 JSONL。
- 保留现有 `RuntimeDumpRunner` 版本握手和旧四类 dump 行为；`RD_VERSION` 升级时同步 README、契约和测试证据。
- 不改 `execute_command` 的权限/危险命令逻辑，不增加模组自动语义映射。
- 实测只涉及用户已授权的 CTI0.46 与 Farming 隔离副本；AC1 在移除 KubeJS 及必需附属 mod 的副本，AC6 在有 KubeJS 副本对同一 dispatcher 做结构化/RCON 探针对照。部署前记录副本脚本、mod 移动清单、端口和运行状态，回滚只恢复隔离副本，不触碰原实例或世界数据。
