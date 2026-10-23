# 实施计划：聊天互通重构

按序执行；每步完成后做对应验证。验证以「导入/编译级 + 单元级临时脚本」为主（本插件无法脱离 AstrBot 环境完整跑通，务实原则不做重型集成测试）。

## Checklist

1. [ ] 新增 `log_watcher.py`：LogWatcher 类（1s 轮询、三判据轮转检测、半行缓冲、UTF-8/GBK 嗅探、daemon 单线程执行器、任务代际防护）；正则从 log_client.py 搬迁五类事件。
   - 验证：临时脚本造一个假 latest.log，启动 watcher，追加聊天/进退服/死亡行，断言回调触发；模拟轮转（文件重建）断言从头读且不丢新行。
2. [ ] 新增 `text_outbound.py`：tellraw JSON 构造 + 1400B UTF-8 字节预算切段 + 转义。
   - 验证：临时脚本对 3000 字中文文本切段，断言每段 ≤1400B 且字符完整。
3. [ ] 新增绑定存储：main.py 内或独立小模块管 chat_bridge.json（读/写/原子替换/失败回滚）。
4. [ ] main.py 改造：
   - 删 LogClient 引用与 log 通道配置读取；initialize() 启动 LogWatcher（mc_server_dir 非空时）；terminate() 停 watcher + 关 RCON。
   - 新增 mc绑定 / mc解绑 / mc喊话 命令（admin 校验、群消息校验、冷却）。
   - _forward_to_bound 推送；mc_message_prefix 生效。
   - _send_fake_event / _send_system_event 的 platform 从绑定 UMO 取；新增 enable_system_event_context 开关。
   - _send_to_mc_chat 改用 text_outbound 切段。
5. [ ] 删除 log_server.py、log_client.py；_conf_schema.json 删 5 个 log 通道配置项、加 enable_system_event_context；rcon_client.py 删 get_online_players。
   - 验证：`python3 -m py_compile` 全目录通过；grep 确认无 log_server_host / LogClient 残留引用。
6. [ ] README 更新：删「手动运行 log_server.py」章节，写新用法（同机自动监听、mc绑定/mc解绑/mc喊话、qqofficial 限制说明）。
7. [ ] 全量自查（trellis-check 视角）：对照 PRD AC1-AC7 逐条核对实现落点。

## Review Gates

- 步骤 1-2 完成后再进 3-4（watcher 与切段是基础件）。
- 全部完成后派 code-review 子代理（对照 PRD/AC + 务实原则），阻塞级问题修完复检一轮。

## Rollback Points

- 每步一个逻辑提交单元（是否 commit 由用户决定）；log_server.py/log_client.py 仅从 git 恢复即可回滚。
