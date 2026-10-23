"""知识库 SQLite 存储层。

定位：items 表只是 mods/*.jar 的**派生缓存**，删掉可完整重建，不构成任何一份真相。
因此每次操作各自 connect/close，不共享模块级连接，也不用 check_same_thread=False
（builder 在 asyncio.to_thread 线程写，查询工具在事件循环线程读）。
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterable
from typing import Any, Optional

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  item_id TEXT PRIMARY KEY,
  namespace TEXT NOT NULL,
  path TEXT NOT NULL,
  kind TEXT NOT NULL,
  has_item INTEGER,
  has_item_guess INTEGER NOT NULL DEFAULT 0,
  name_en TEXT,
  name_zh TEXT,
  zh_source TEXT,
  mod_name TEXT
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""


@contextmanager
def _connect(db_path: str):
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def is_built(db_path: str) -> bool:
    """库文件存在且 meta 里有构建时间，才算已构建。"""
    if not os.path.isfile(db_path):
        return False
    try:
        with _connect(db_path) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'build_time'").fetchone()
        return bool(row)
    except sqlite3.Error:
        return False


def write(db_path: str, rows: Iterable[dict[str, Any]], meta: dict[str, Any]):
    """全量重建：单事务内 DELETE + executemany，重复重建不会长出重复行。"""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM meta")
        conn.executemany(
            "INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    r["id"],
                    r["namespace"],
                    r["path"],
                    r["kind"],
                    r.get("has_item"),
                    int(r.get("has_item_guess") or 0),
                    r.get("name_en"),
                    r.get("name_zh"),
                    r.get("zh_source"),
                    r.get("mod_name"),
                )
                for r in rows
            ],
        )
        conn.executemany(
            "INSERT INTO meta VALUES (?,?)",
            [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()],
        )
        conn.commit()


def load_meta(db_path: str) -> Optional[dict[str, Any]]:
    """读取 meta 表；库不存在或为空返回 None。"""
    if not os.path.isfile(db_path):
        return None
    try:
        with _connect(db_path) as conn:
            rows = conn.execute("SELECT key, value FROM meta").fetchall()
    except sqlite3.Error:
        return None
    if not rows:
        return None
    out: dict[str, Any] = {}
    for key, value in rows:
        try:
            out[key] = json.loads(value)
        except (TypeError, ValueError):
            out[key] = value
    return out


def search(db_path: str, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
    """中文名 / 英文名 / 完整 ID 模糊搜索，排序：完全匹配 > 前缀 > 包含。"""
    kw = (keyword or "").strip()
    if not kw:
        return []
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 10
    # LIKE 里的 % / _ 要转义，否则 "diamond_sword" 里的下划线会被当通配符
    like = kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    exact = kw
    prefix = like + "%"
    contains = "%" + like + "%"
    sql = """
    SELECT item_id, namespace, path, kind, has_item, has_item_guess,
           name_en, name_zh, zh_source, mod_name
    FROM items
    WHERE item_id LIKE ? ESCAPE '\\' OR name_zh LIKE ? ESCAPE '\\' OR name_en LIKE ? ESCAPE '\\'
    ORDER BY CASE
        WHEN item_id = ? OR name_zh = ? OR name_en = ? THEN 0
        WHEN item_id LIKE ? ESCAPE '\\' OR name_zh LIKE ? ESCAPE '\\' OR name_en LIKE ? ESCAPE '\\' THEN 1
        ELSE 2 END,
      namespace, item_id
    LIMIT ?
    """
    params = (contains, contains, contains, exact, exact, exact, prefix, prefix, prefix, limit)
    with _connect(db_path) as conn:
        cur = conn.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
