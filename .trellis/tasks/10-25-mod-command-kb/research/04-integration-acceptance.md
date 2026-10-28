# 阶段 7 最终集成验收（2026-10-28）

结论：**通过**。两个生产者（KubeJS 主路径、RCON help 回退）共用同一快照契约、同一条查询消费链，
查询改进不按 producer 分叉；无快照时原版兜底与去重保持；父 PRD AC1–AC7 均有可核对证据。

## 验收环境与证据源

不启服务器、不重启线上 AstrBot，使用 P6 真机验收留下并已发布过的真实产物（文件路径按阶段 9 计划会被清理，SHA-256 已记录在下表），跑生产代码
（`kb/commands.py` 的 `validate_snapshot` / `publish_snapshot` / `search_commands`）。

| 产物 | 路径 | producer | 条目/根 | SHA-256 |
|---|---|---|---|---|
| CTI KubeJS 快照（1.19.2，P6 AC6 14:37 `/mc_kb_dump`） | `/home/guigui/mc/rcon-help-probe/CTI-kubejs/runtime_dump/commands.json` | `kubejs` | 2061 / 188 | `4ff23bd7…62c73c8` |
| CTI RCON 快照（1.19.2，P6 AC1 14:33 `/mc_kb_rcon_scan`） | `/tmp/p6-cti-h7no395z/runtime_dump/commands.json` | `rcon` | 474 / 161（条目内根；扫描根 179，含未发布的纯根） | `8b50e867…49db88d` |
| Farming KubeJS 快照（1.20.1） | `/home/guigui/mc/rcon-help-probe/Farming-kubejs/runtime_dump/commands.json` | `kubejs` | 2248 / 193 | `44c7ee00…50abd1` |

验收脚本：`research/p7-integration-check.py`（只读上述文件、写临时数据目录；阶段 9 清理这些遗留快照后，重跑需先重新生成快照）。
脚本 9 组断言全部 PASS。

## 1. 单一快照契约

- 两份真实快照都通过同一个 `validate_snapshot()`：`producer` 分别为 `kubejs` / `rcon`，`count` 与
  `entries` 数一致；Farming 1.20.1 的 2248 条同样通过。
- producer 枚举即 `SNAPSHOT_PRODUCERS = ("kubejs", "rcon")`，没有 producer 专属字段或分支 schema。
- 非法 producer、`count` 不一致、`syntax` 与 `name` 不一致都被同一入口拒绝（失败关闭无法绕过）。

## 2. 单一消费链

- 查询入口只有 `kb/commands.py:search_commands()`；`main.py:tool_search_mc_commands()` 是唯一调用方。
- 发布入口收敛到同一对函数：KubeJS 走 `import_snapshot()` → `validate_snapshot()` + `publish_snapshot()`；
  RCON 主指令在锁外调用同名 `validate_snapshot()` + `publish_snapshot()`。两条路径写同一个
  `runtime_dump/commands.json`，没有第二套文件格式或消费链。
- producer 在消费侧只影响一段降级提示（`_runtime_note`）和快照校验枚举，不参与匹配、排序、去重。

## 3. 两种 producer 使用同一查询改进

用真实快照分别发布后执行同一批查询：

| 检查 | KubeJS | RCON |
|---|---|---|
| `/advancement` 命中 + 单根只出现一次 | ✅ | ✅ |
| 降级提示符合各自语法可信度（KJS「已注册不代表必然可执行」/ RCON「深层分支是压缩语法」） | ✅ | ✅ |
| 中文 desc「封禁」命中运行时同根，继承内置 desc，来源/权限仍显示未知 | ✅ | ✅ |
| 多 token AND（`advancement grant`） | ✅ | ✅ |
| 无快照时内置 `/ban` 可搜到、不追加运行时提示 | ✅ | ✅ |
| 运行时同根合并后不与内置条目重复 | ✅ | ✅ |

**producer 不感知验证**：把 KubeJS 快照的 `producer` 改成 `rcon` 后重新校验并发布（共享契约接受），
同一查询在去掉提示行后与 KubeJS 输出**逐字一致**——匹配、排序、去重逻辑不分叉，只有提示文案随
producer 变化。

## 4. 失败关闭与跨机复制

- 坏 producer / `count` 不符 / `name`-`syntax` 不符：`validate_snapshot` 返回 `(None, 原因)`。
- 跨机只复制 `runtime_dump/commands.json` 到另一数据目录即可查询，producer 保持 `rcon`，
  说明快照没有 producer 专属依赖（跨机流程沿用 P6 AC1/AC6 实测）。
- 本地化错误输出（`未知的命令`）在根级与 targeted 解析都被拒绝，已补进离线用例。
- 传输/解析失败保留旧快照、普通命令不被污染等由 P6 真机证据 +
  `tests/test_rcon_help.py`（54 例）覆盖，详见子任务证据
  `.trellis/tasks/10-25-rcon-help-command-fallback/research/03-live-acceptance.md`。

## 5. 文档与 spec 一致性

逐条比对 README「命令知识库」两节、`spec/backend/runtime-dump.md` §3.1.2 与代码：

| 声明 | 代码/实测 |
|---|---|
| 请求预算 `2N+4`（N 个逐根 help + 首末根 help，每次 help 配 B） | `rcon_help.py:490` `expected_requests = 2 * (len(roots) + 2)`；实测 CTI 362/179、Farming-minimal 168/82、AC6 370/183 全部吻合 |
| 尾随窗口约 1.5 秒，窗口内有包即失败 | `ScanLimits.trailing_window = 1.5` |
| 内部上限（根数/片数/字节/总片数/总字节/交换与总超时）且不新增用户配置 | `ScanLimits` 全部为模块内默认值 |
| 纯根可能未收录、targeted 空响应不回填 | RCON 快照无 `syntax == root` 的纯根条目；KubeJS 快照保留 `chunks` 等纯根条目 |
| 入口不受 `kb.enabled` 限制、跨机不要求本机目录 | `cmd_kb_rcon_scan` 只检查 `self.kb is None`，不读 `kb.enabled` |
| KubeJS 本体证据只认 `[[mods]]`/fabric id，可选依赖不算 | `_toml_declares_kubejs` + 入口用例；已对 4 个真实副本核对 |
| 失败保留旧快照、原子替换 | 同一 `publish_snapshot` + P6 AC1 旧快照 hash 不变 |

发现的唯一文档瑕疵：README 中 `2N+4` 的组成写成「每根一个 help 加一个 B 哨兵，首末根 help 各一次」，
字面只合计 `2N+2`，与代码/spec 不符。已改为「N 个逐根 help 加首末根 help 各一次，每次 help 都配一个
B 哨兵」，CRLF 保持不变。

## 6. 全量验证命令

```text
python -m compileall main.py rcon_client.py rcon_help.py runtime_dump.py tools/ kb/ tests/   → OK
node --check assets/runtime_dump.js                                                          → OK
python -m unittest discover -s tests                                                         → 109 tests OK（含本任务 54 例，含中文本地化错误文本拒绝）
ruff check rcon_help.py tests/test_rcon_help.py                                              → All checks passed
ruff format --check rcon_help.py tests/test_rcon_help.py                                     → 2 files already formatted
ruff check main.py rcon_client.py（工作区 vs HEAD 基线）                                      → 均 162 例，新增行 0 例（main +226 / rcon_client +24 / kb/commands +1）
git -c core.whitespace=cr-at-eol diff --check                                                → 无输出（CRLF 文件不误报）
```

## 7. 边界与未尽事项

- 未重启线上 AstrBot，未经过 AstrBot 消息分发层；入口验证沿用 P6 的生产方法级口径
  （真实 RCON + 真实 KnowledgeBase + 真实发布），协议故障穷举仍由离线 fake server 覆盖。
- RCON 快照条目内根 161 < 扫描根 179，是设计的「纯根可能未收录」，不是数据丢失；
  P6 AC6 证据中的 `rcon_pure_roots` 是同一事实的另一种计数。
- 父任务阶段 8（提交）待用户明确要求；阶段 9（清理 probe 目录）在父任务归档后执行，
  本次验收引用到的 `rcon-help-probe` 与 `/tmp` 文件在清理前保持不动。

## 8. 父 AC 证据索引

| AC | 证据 |
|---|---|
| AC1 主路径 | 本文 §1/§3/§5（KubeJS 真实快照 2061 条查询）；P6 AC6（dump 计数 + 物品/方块/实体/流体不回归）；归档子任务一 `implement.md` |
| AC2 无 KubeJS fallback | P6 AC1/AC2（CTI-nokubejs 474 条、Farming-minimal `wine age <years>`）；本文 §1/§3；子任务 `research/03-live-acceptance.md` |
| AC3 原版兜底 | 本文 §3（无快照 `/ban`、运行时同根不重复）；归档子任务一 AC4 |
| AC4 元数据边界 | 本文 §3（继承 desc、来源/权限未知）；KubeJS 完整 usage vs RCON 压缩语法提示；归档子任务一 AC4 |
| AC5 失败安全 | P6 AC4 真机（旧快照 hash 不变、取消释放锁/socket）+ `tests/test_rcon_help.py` 54 例；本文 §4 |
| AC6 验证与文档 | 109 tests、README 两节 + `runtime-dump.md` §3.1.2；本文 §5 |
| AC7 中文意图检索 | 归档 `10-26-command-intent-search/research/02-live-ac4.md`：真实模型 5/5；AC1–AC5 勾选 |
