"""
长期记忆数据库模块：SQLite 存储用户跨会话的精确事实。
每条记忆绑定 device_id，支持 upsert（同设备同维度同事实自动覆盖）。
"""
import os
import sqlite3
import threading
from datetime import datetime
from typing import List, Dict, Optional

from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

# 数据库路径：项目 data/ 目录下
_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
_DB_PATH = os.path.join(_DB_DIR, "memory.db")

# 线程本地存储（SQLite 连接不能跨线程）
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """获取当前线程的 SQLite 连接（懒初始化）。"""
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(_DB_DIR, exist_ok=True)
        _local.conn = sqlite3.connect(_DB_PATH, timeout=10)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _init_tables(_local.conn)
    return _local.conn


def _init_tables(conn: sqlite3.Connection):
    """创建表和索引（幂等）。"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            fact TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_device_category_fact
            ON user_memories(device_id, category, fact);
        CREATE INDEX IF NOT EXISTS idx_device_id
            ON user_memories(device_id);
    """)
    conn.commit()


def upsert_memory(device_id: str, category: str, fact: str) -> bool:
    """
    存入或覆盖一条记忆。
    同 (device_id, category, fact) 组合已存在时更新 updated_at。
    """
    if not device_id or not fact:
        return False
    category = (category or "general").strip().lower()
    fact = fact.strip()
    if not fact:
        return False
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO user_memories (device_id, category, fact, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(device_id, category, fact) "
            "DO UPDATE SET updated_at = excluded.updated_at",
            (device_id, category, fact, datetime.now().isoformat()),
        )
        conn.commit()
        logger.bind(tag=TAG).debug(f"记忆已保存: [{category}] {fact[:50]}...")
        return True
    except Exception as e:
        logger.bind(tag=TAG).error(f"保存记忆失败: {e}")
        return False


def search_memory(device_id: str, keyword: str, limit: int = 3) -> List[Dict]:
    """
    模糊搜索记忆，按时间倒序，最多返回 limit 条。
    返回 [{"category": "...", "fact": "...", "updated_at": "..."}]
    """
    if not device_id or not keyword:
        return []
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT category, fact, updated_at FROM user_memories "
            "WHERE device_id = ? AND fact LIKE ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (device_id, f"%{keyword}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.bind(tag=TAG).error(f"查询记忆失败: {e}")
        return []


def get_all_memories(device_id: str, limit: int = 50) -> List[Dict]:
    """获取某设备的所有记忆（调试用）。"""
    if not device_id:
        return []
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT category, fact, updated_at FROM user_memories "
            "WHERE device_id = ? ORDER BY updated_at DESC LIMIT ?",
            (device_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.bind(tag=TAG).error(f"获取记忆失败: {e}")
        return []


def delete_memory(device_id: str, fact: str) -> bool:
    """删除一条记忆。"""
    if not device_id or not fact:
        return False
    try:
        conn = _get_conn()
        conn.execute(
            "DELETE FROM user_memories WHERE device_id = ? AND fact = ?",
            (device_id, fact.strip()),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.bind(tag=TAG).error(f"删除记忆失败: {e}")
        return False


def get_memories_by_device(device_id: str) -> List[Dict]:
    """获取某设备的所有记忆（含 id），供管理 UI 使用。"""
    if not device_id:
        return []
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id, device_id, category, fact, updated_at FROM user_memories "
            "WHERE device_id = ? ORDER BY updated_at DESC",
            (device_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.bind(tag=TAG).error(f"获取设备记忆失败: {e}")
        return []


def get_all_memories_for_admin() -> List[Dict]:
    """获取所有设备的全部记忆（含 id），供管理 UI 使用。"""
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id, device_id, category, fact, updated_at FROM user_memories "
            "ORDER BY updated_at DESC",
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.bind(tag=TAG).error(f"获取全部记忆失败: {e}")
        return []


def delete_memory_by_id(memory_id: int) -> bool:
    """按 id 删除一条记忆。"""
    try:
        conn = _get_conn()
        conn.execute("DELETE FROM user_memories WHERE id = ?", (memory_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.bind(tag=TAG).error(f"按 id 删除记忆失败: {e}")
        return False


def delete_memories_by_device(device_id: str) -> int:
    """清空某设备的全部记忆，返回删除条数。"""
    if not device_id:
        return 0
    try:
        conn = _get_conn()
        cursor = conn.execute(
            "DELETE FROM user_memories WHERE device_id = ?", (device_id,)
        )
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        logger.bind(tag=TAG).error(f"清空设备记忆失败: {e}")
        return 0
