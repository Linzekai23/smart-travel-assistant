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
