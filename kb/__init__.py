"""物品知识库门面。

知识库是 mods 目录的派生缓存：删掉可完整重建，不影响服务器状态，也不构成第二份真相。
"""

import os

try:
    from astrbot.api import logger
except ImportError:  # 允许脱离 AstrBot 环境独立测试/复现（脚本直跑）
    import logging

    logger = logging.getLogger("mc_manager.kb")

from . import builder, commands, query, store

__all__ = ["KnowledgeBase"]


def _with_command_note(text: str, cmd_info: dict) -> str:
    """物品重建失败时，命令快照的成功导入或告警仍要说清楚。"""
    notes = []
    if cmd_info.get("status") == "published":
        notes.append(
            "（命令快照已单独导入：%d 条用法 / %d 个根命令，物品知识库仍失败）"
            % (cmd_info.get("count", 0), cmd_info.get("roots", 0))
        )
    if cmd_info.get("warning"):
        notes.append("⚠️ " + cmd_info["warning"])
    return text + ("\n" + "\n".join(notes) if notes else "")


class KnowledgeBase:
    """持有配置与数据库路径，向 main.py 提供重建 / 查询 / 状态接口。"""

    def __init__(self, data_dir: str, server_dir: str = "", mc_version: str = "",
                 client_dir: str = "", vanilla_zh_download: bool = True,
                 cfpa_auto_download: bool = True):
        self.data_dir = str(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        self.server_dir = (server_dir or "").strip()
        self.mc_version = (mc_version or "").strip()
        self.client_dir = (client_dir or "").strip()
        self.vanilla_zh_download = bool(vanilla_zh_download)
        self.cfpa_auto_download = bool(cfpa_auto_download)
        self.db_path = os.path.join(self.data_dir, "items.db")

    @property
    def enabled(self):
        return bool(self.server_dir)

    def rebuild(self, log=None) -> str:
        """阻塞重建（调用方应放到 asyncio.to_thread 里跑），返回回执文案。"""
        # 命令快照先于物品重建导入：物品扫描可能失败，命令快照本身仍是独立有效的派生数据
        cmd_info = commands.import_snapshot(self.server_dir, self.data_dir)
        try:
            stats = builder.rebuild(
                server_dir=self.server_dir,
                data_dir=self.data_dir,
                db_path=self.db_path,
                mc_version=self.mc_version,
                client_dir=self.client_dir,
                vanilla_zh_download=self.vanilla_zh_download,
                cfpa_auto_download=self.cfpa_auto_download,
                log=log,
            )
        except ValueError as exc:  # 配置/环境错误（用 ValueError，不引入自定义异常类）
            logger.warning("物品知识库重建失败: %s", exc)
            return _with_command_note("❌ 知识库重建失败：%s" % exc, cmd_info)
        except Exception as exc:  # 重建失败不能拖垮插件，把原因原样带回给管理员，堆栈进日志
            logger.exception("物品知识库重建异常")
            return _with_command_note("❌ 知识库重建异常：%s" % exc, cmd_info)
        stats["commands"] = cmd_info
        if cmd_info.get("warning"):
            # 命令快照问题只作为告警展示，不阻断物品重建
            stats.setdefault("warnings", []).insert(0, cmd_info["warning"])
        return query.format_rebuild(stats)

    def search(self, keyword: str, limit: int = 10) -> str:
        """返回给 LLM 的查询文案。"""
        if not self.enabled:
            return ("物品知识库未配置：请管理员在插件配置里填写 mc_server_dir（MC 服务器根目录）"
                    "并运行 /mc_kb_rebuild。")
        if not store.is_built(self.db_path):
            return query.format_not_built()
        try:
            limit = max(1, min(int(limit), 30))
        except (TypeError, ValueError):
            limit = 10
        rows = store.search(self.db_path, keyword, limit)
        return query.format_search(keyword, rows, limit)

    def status(self) -> str:
        if not self.enabled:
            return ("物品知识库未配置：请管理员在插件配置里填写 mc_server_dir（MC 服务器根目录）"
                    "并运行 /mc_kb_rebuild。")
        return query.format_status(store.load_meta(self.db_path))
