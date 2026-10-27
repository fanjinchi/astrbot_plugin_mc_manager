# 父任务执行计划

父任务负责契约和集成，不替代三个子任务分别实施、验证和归档。

## 阶段顺序

- [ ] 1. 审批父设计与子任务一计划；只启动 `10-25-kubejs-command-dump`。
- [ ] 2. 子任务一交付：共享 `commands.json` schema、KubeJS 导出、原子发布、查询聚合、新建 `tests/` 离线回归及 CTI/Farming 实测。
- [ ] 3. 对子任务一做 spec + standards review 和 `trellis-check`；发现问题回原任务修正，通过后再归档。
- [ ] 4. 子任务一归档后分别评审后续任务启动条件；同一阶段只保留一个实施者，不并行修改产品代码。`10-25-rcon-help-command-fallback` 已补 design.md / implement.md，但必须完成双版本隔离副本 A/B、多包、空包和共享锁实测后才能 start；`10-26-command-intent-search` 代码依赖已完成，可先 start 做 AC1–AC3/AC5，AC4 所需两份真实快照必须重新生成、分别发布并完成同一 AstrBot 模型 5/5 后才能完成/归档。
- [ ] 5. RCON 子任务复用同一发布/查询契约，以独立 `/mc_kb_rcon_scan` 完成无 KubeJS 闭环、A/B 传输、纯根降级、可检验故障关闭、双版本分环境差分与 `2N+4` 性能记录。
- [ ] 6. 检索子任务完成英文调用引导、token AND、离线回归和实际 AstrBot 模型 5/5 召回；失败返回规划，不自动扩建中文语义层。
- [ ] 7. 父任务做最终集成验收：两个生产者不会留下第二套消费链，两种 producer 都使用同一查询改进，文档和 spec 一致，全部 AC 有证据。
- [ ] 8. 仅在用户明确要求时提交；父任务在所有子任务验收后归档。

## 总体验证命令

```bash
python3 -m compileall -q main.py rcon_client.py runtime_dump.py tools/ kb/ tests/
node --check assets/runtime_dump.js
python3 -m unittest discover -s tests -v
ruff format <本次新增或改动的 Python 文件>
ruff check <本次新增或改动的 Python 文件>
```

- `tests/` 由子任务一新建（标准库 unittest + 临时目录夹具）。AstrBot 根项目已配置 ruff，验收必须对本次新增/改动的 Python 文件运行 ruff format/check，不做全仓 reformat；不引入 pytest 或新运行时依赖。`quality-guidelines` 已记录测试套件与 lint 现状，后续保持同步。
- 真机验证以各子任务记录为准；编译和离线夹具不能替代服务器证据。
- 父任务集成检查至少在有 KubeJS 隔离副本比较同一 dispatcher 的 KubeJS/RCON 探针根集合与一级子命令 usage 集合（深层压缩和纯根缺失单独记录），并在无 KubeJS 副本验收生产入口及 RCON 后普通命令响应未被污染。

## Review gates

- 子任务一边界：不改变现有四类 dump、物品搜索、RCON 普通命令语义。
- 子任务二边界：不在每次 execute/search 前扫描，不自动替代 KubeJS 主路径，不发布部分快照；不得立即连写 A+B、以 idle-drain 判完整、从空 targeted/根级 `/foo` 伪造纯根，或承诺排除同根集 reload/任意中间删片。
- 子任务三边界：不改快照 schema，不承诺模组中文直搜，不引入自动中文、同义词、rerank 或语义层；真实验收只检索，不执行 MC 命令。历史 count/root 数不能替代 AC4 新快照、hash 和逐项 syntax，5/5 未完成不得归档。
- 父任务最终检查 PRD AC1–AC7、文档路径、RD_VERSION、跨机命令快照复制（不扩张为完整物品迁移）和回滚说明。

## Rollback

- 每阶段独立回滚代码和派生快照；服务器脚本按子任务备份恢复。
- 若共享 schema 必须变更，回到父设计并同时评估两个生产者及查询，不允许子任务二私改契约。
