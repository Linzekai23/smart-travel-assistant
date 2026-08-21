import json

import pytest

from app import db


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAVEL_DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    yield


def test_create_and_get_session(tmp_db):
    sid = db.create_session()
    assert db.get_session(sid)["id"] == sid


def test_get_unknown_session_returns_none(tmp_db):
    assert db.get_session("nope") is None


def test_message_roundtrip(tmp_db):
    sid = db.create_session()
    db.add_message(sid, "user", "10月去东京3天预算8000")
    db.add_message(sid, "assistant", "好的，正在规划")
    msgs = db.list_messages(sid)
    assert msgs == [
        {"role": "user", "content": "10月去东京3天预算8000"},
        {"role": "assistant", "content": "好的，正在规划"},
    ]


def test_add_message_with_trip_and_get_latest(tmp_db):
    sid = db.create_session()
    db.add_message(sid, "user", "你好")
    db.add_message(sid, "assistant", "回复1")
    db.add_message(sid, "user", "第二天换成博物馆")
    trip = {"itinerary": {"days": [{"day": 1, "title": "博物馆日", "weather_note": "",
                                    "items": []}]}, "budget_plan": {"items": [], "total": None}}
    db.add_message(sid, "assistant", "回复2", trip_json=json.dumps(trip, ensure_ascii=False))
    assert db.get_latest_trip(sid) == trip  # 最新一条非空 trip


def test_get_latest_trip_none_without_trip(tmp_db):
    sid = db.create_session()
    db.add_message(sid, "user", "你好")
    db.add_message(sid, "assistant", "好的")
    assert db.get_latest_trip(sid) is None


def test_get_latest_trip_unknown_session_none(tmp_db):
    assert db.get_latest_trip("nope") is None


def test_migration_adds_trip_json_column(tmp_path, monkeypatch):
    """M4 前旧库（无 trip_json 列）→ init_db 自动 ALTER 补列，既有数据不破坏。"""
    import sqlite3
    db_path = tmp_path / "old.db"
    monkeypatch.setenv("TRAVEL_DB_PATH", str(db_path))
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO sessions (id) VALUES ('oldsid');
        INSERT INTO messages (session_id, role, content) VALUES ('oldsid', 'user', '旧消息');
    """)
    conn.commit()
    conn.close()
    db.init_db()
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
    conn.close()
    assert "trip_json" in cols
    assert db.list_messages("oldsid") == [{"role": "user", "content": "旧消息"}]
