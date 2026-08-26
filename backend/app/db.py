import json
import os
import sqlite3
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    trip_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS trips (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    title TEXT NOT NULL,
    trip_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_conn() -> sqlite3.Connection:
    path = Path(os.environ.get("TRAVEL_DB_PATH", "data/travel.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        # M4 前旧库迁移：messages 表缺 trip_json 列 → ALTER 补列（既有数据不破坏）
        cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
        if "trip_json" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN trip_json TEXT")
        conn.commit()
    finally:
        conn.close()


def create_session() -> str:
    sid = uuid.uuid4().hex
    conn = get_conn()
    try:
        conn.execute("INSERT INTO sessions (id) VALUES (?)", (sid,))
        conn.commit()
    finally:
        conn.close()
    return sid


def get_session(sid: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def add_message(sid: str, role: str, content: str, trip_json: str | None = None) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, trip_json) VALUES (?, ?, ?, ?)",
            (sid, role, content, trip_json),
        )
        conn.commit()
    finally:
        conn.close()


def list_messages(sid: str) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
            (sid,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_latest_trip(sid: str) -> dict | None:
    """最新一条非空结构化行程（重排语义：仅最新行程有效，旧行程被整体覆盖）。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT trip_json FROM messages WHERE session_id = ? AND trip_json IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
    finally:
        conn.close()
    return json.loads(row["trip_json"]) if row else None


# ---------------------------------------------------------------------------
# trips：行程快照（"我的行程"列表；user_id 预留多用户，当前恒为 'default'）
# ---------------------------------------------------------------------------


def create_trip(trip_id: str, title: str, trip_json: dict, user_id: str = "default") -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO trips (id, user_id, title, trip_json) VALUES (?, ?, ?, ?)",
            (trip_id, user_id, title, json.dumps(trip_json, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def _get_trip_row(trip_id: str, user_id: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_trip(trip_id: str, user_id: str = "default") -> dict | None:
    """单行程详情（trip_json 已反序列化）。"""
    row = _get_trip_row(trip_id, user_id)
    if not row:
        return None
    row["trip_json"] = json.loads(row["trip_json"])
    return row


def list_trips(user_id: str = "default") -> list[dict]:
    """行程列表（按更新时间倒序，不含 trip_json 大字段，附 days 天数供卡片展示）。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, trip_json, created_at, updated_at FROM trips "
            "WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    result = []
    for r in rows:
        d = dict(r)
        days = None
        try:
            itinerary = json.loads(d["trip_json"]).get("itinerary") or {}
            days = len(itinerary.get("days", [])) if isinstance(itinerary, dict) else None
        except Exception:
            days = None
        d["days"] = days
        d.pop("trip_json", None)
        result.append(d)
    return result


def delete_trip(trip_id: str, user_id: str = "default") -> bool:
    conn = get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
