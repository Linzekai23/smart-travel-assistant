import os

import pytest

from app import db


@pytest.fixture()
def tmp_db(tmp_path):
    os.environ["TRAVEL_DB_PATH"] = str(tmp_path / "test.db")
    db.init_db()
    yield
    del os.environ["TRAVEL_DB_PATH"]


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
