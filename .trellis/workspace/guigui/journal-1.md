# Journal - guigui (Part 1)

> AI development session journal
> Started: 2026-10-21

---



## Session 1: 物品知识库评审与修复收尾
<!-- trellis-session: v=2 fp=1b691f3dff087f84 -->

**Date**: 2026-10-23
**Task**: 物品知识库评审与修复收尾
**Branch**: `master`

### Summary

双轴代码评审（Standards+Spec 子代理 + 主会话复核）确认实现无阻塞问题、既有 30 工具零回归；修复 4 个评审发现：幻影 minecraft 条目剔除（Farming 实测 -144 条，mace/breeze_rod 归零）、重建失败路径补日志（含脱离 AstrBot 的 logging 回退）、数据目录名改为插件全名（旧目录已迁移）、typing 旧泛型改内建。幻影条目约定写入 database-guidelines spec。任务已归档。

### Git Commits

| Hash | Message |
|------|---------|
| `73c9545` | fix(知识库): 剔除幻影原版条目并为重建失败路径补日志 |
| `18cab86` | fix(插件): 修正知识库数据目录名为插件全名 |
| `ef41972` | style(知识库): 改用内建泛型替代 typing 旧泛型 |
| `c472d09` | docs(spec): 记录原版验证集过滤幻影条目的约定 |

### Status

[OK] **Completed**


## Session 2: LLM工具精简（30→12）+ 原版命令知识库 + 删除脚本执行器
<!-- trellis-session: v=2 fp=c90296e289593bee -->

**Date**: 2026-10-23
**Task**: LLM工具精简（30→12）+ 原版命令知识库 + 删除脚本执行器
**Branch**: `master`

### Summary

评估并落地两项需求：① 工具从30精简到12（17个低频薄封装走execute_command兜底，whitelist/banlist收回管理员），新增search_mc_commands内置原版命令知识库（74条JSON+kb/commands.py，预留mod命令合并入口issue #5）；② 删除execute_script/script_executor.py（exec全量builtins+默认配置权限失效=RCE），多步任务由AstrBot电脑使用能力承接。双轴评审（Standards/Spec）无P0，2个P1（spec文档失真、send_to_qq_group缺权限检查）与4个P2全部修复，复查轮通过。另建issue #5（mod命令导入知识库），修正issue-tracker文档gh需显式-R。

### Git Commits

| Hash | Message |
|------|---------|
| `dbcf66c` | feat(工具): 精简LLM工具至12个并新增原版命令知识库，移除脚本执行器 |
| `03ba4f9` | docs(spec): 同步工具精简后的目录结构与规范 |
| `2225539` | docs(agents): 修正 gh 需显式指定 fork 仓库的说明 |

### Status

[OK] **Completed**

## 2026-10-23 聊天互通重构（chat-bridge-local-log）

- 删除 log_server.py/log_client.py 双进程 TCP 通道，改为 log_watcher.py 插件内直读 mc_server_dir/logs/latest.log（同机）
- 新增 text_outbound.py：RCON 1460B 静默拔线 → 原文预算一半切段（转义最坏 2 倍膨胀）
- mc绑定/mc解绑 命令写 unified_group_umo + config.save_config()（database-guidelines：不新增 JSON 存状态）
- mc喊话 限绑定群 + 5s/人冷却；系统事件转发不受 enable_system_event_context 控制（那是注入 LLM 上下文的开关）
- 关键坑：aiomcrcon send_cmd 返回 tuple[str,int]，execute_async 必须解包（本轮 P0）
- 两轮子代理 review：第一轮 1 个 P0（tuple.startswith），第二轮确认修复合规、无新增阻塞
- 待真机验证：AC2（真实群绑定/转发/喊话链路）；qq_official 主动推送限制已写 README


## Session 3: 聊天互通重构：本地日志直连 + Forge 兼容与绑定安全修复
<!-- trellis-session: v=2 fp=9b8a6397c7575fd3 -->

**Date**: 2026-10-24
**Task**: 聊天互通重构：本地日志直连 + Forge 兼容与绑定安全修复
**Branch**: `master`

### Summary

删除 log_server.py/log_client.py 双进程 TCP 通道，改为插件内 LogWatcher 直读 mc_server_dir/logs/latest.log；新增 mc绑定/mc解绑/mc喊话（写 unified_group_umo 配置）、MC→QQ 前缀转发与 text_outbound RCON 字节预算切段；两轮独立评审 + 真机日志核对后修复 Forge/NeoForge 系统事件解析（logger 段兼容、死亡句式收紧）与 MC 伪造事件触发 QQ 绑定命令的安全缺口，并补齐 RCON 连接类异常重连。

### Main Changes

- 删除 TCP 日志通道与 5 个 log 配置项，新增 log_watcher.py / text_outbound.py
- 新增群绑定命令与 mc喊话，MC→QQ 转发默认需 mc_bridge_prefix 前缀，系统事件照常转发
- 修复：Forge 日志 [logger/] 段导致进退服/死亡/成就解析全失效；MC 聊天伪造事件可触发 mc绑定/mc解绑/mc喊话
- 修复：aiomcrcon 连接异常纳入重连重试；同步 README / AC2 / design / backend spec

### Git Commits

| Hash | Message |
|------|---------|
| `3116aa6` | feat(聊天互通): 改为本地日志直连并新增群绑定、mc喊话与转发前缀 |
| `faecb9f` | fix(聊天互通): 兼容 Forge 日志解析并拦截 MC 伪造事件触发绑定命令 |

### Testing

- [OK] 真实 Forge 日志 10,904 行：join 12 / leave 9 / advancement 41 / death 2 / chat 21，与原始日志逐类一致，实体死亡与 stack trace 无误报
- [OK] log_watcher 行为回归（不回放、半行、轮转/重建、stop 无幽灵任务）、text_outbound 切段、RCON fake-client 重连、py_compile/JSON/CRLF 全通过

### Status

[OK] **Completed**

### Next Steps

- 重载 AstrBot 后真机验证群内进退服/死亡/成就推送与 mc绑定/mc喊话 全链路
