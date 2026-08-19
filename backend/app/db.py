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
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_conn() -> sqlite3.Connection:
    path = Path(os.environ.get("TRAVEL_DB_PATH", "data/travel.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
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


def add_message(sid: str, role: str, content: str) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (sid, role, content),
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
