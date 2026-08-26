"""trips（行程快照）测试：db 层 + API 层。"""
import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAVEL_DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    yield


@pytest.fixture(autouse=True)
def _no_real_provider(monkeypatch):
    """TestClient lifespan 强制走"未配置"分支：本机若配了 DEEPSEEK_API_KEY，
    真实 get_provider 会创建模块级单例，污染 test_deepseek.py 的无 key 断言。"""
    def _raise() -> None:
        raise RuntimeError("缺少环境变量 DEEPSEEK_API_KEY（DeepSeek 平台申请后配置）")
    monkeypatch.setattr("app.main.get_provider", _raise)


SAMPLE_TRIP = {
    "itinerary": {"days": [{"day": 1, "title": "第一天", "weather_note": "", "items": []}]},
    "budget_plan": {"items": [], "total": None},
}


# ---------------------------------------------------------------------------
# db 层
# ---------------------------------------------------------------------------


def test_create_and_get_trip(tmp_db):
    db.create_trip("t1", "北京之旅", SAMPLE_TRIP)
    trip = db.get_trip("t1")
    assert trip["title"] == "北京之旅"
    assert trip["trip_json"] == SAMPLE_TRIP
    assert trip["user_id"] == "default"


def test_get_unknown_trip_none(tmp_db):
    assert db.get_trip("nope") is None


def test_list_trips_sorted_by_updated_and_days(tmp_db):
    trip2 = {
        "itinerary": {"days": [{"day": 1, "title": "d1", "weather_note": "", "items": []},
                               {"day": 2, "title": "d2", "weather_note": "", "items": []}]},
        "budget_plan": {"items": [], "total": None},
    }
    db.create_trip("t1", "北京之旅", SAMPLE_TRIP)
    db.create_trip("t2", "成都之旅", trip2)
    # 同秒创建时 updated_at 相同排序不稳定：显式把 t1 改为更旧，制造确定性先后
    conn = db.get_conn()
    try:
        conn.execute("UPDATE trips SET updated_at = datetime('now', '-1 day') WHERE id = 't1'")
        conn.commit()
    finally:
        conn.close()
    trips = db.list_trips()
    assert [t["id"] for t in trips] == ["t2", "t1"]  # updated_at 倒序
    assert trips[0]["days"] == 2
    assert trips[1]["days"] == 1
    assert "trip_json" not in trips[0]  # 列表不带大字段


def test_list_trips_handles_bad_trip_json(tmp_db):
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO trips (id, title, trip_json) VALUES (?, ?, ?)",
            ("bad", "坏数据", "not-json"),
        )
        conn.commit()
    finally:
        conn.close()
    assert db.list_trips()[-1]["days"] is None  # 解析失败降级，不抛


def test_delete_trip(tmp_db):
    db.create_trip("t1", "北京之旅", SAMPLE_TRIP)
    assert db.delete_trip("t1") is True
    assert db.get_trip("t1") is None
    assert db.delete_trip("t1") is False  # 重复删除返回 False


# ---------------------------------------------------------------------------
# API 层
# ---------------------------------------------------------------------------


def test_api_trips_crud(tmp_db):
    with TestClient(app) as c:
        # 创建
        resp = c.post("/api/trips", json={"title": "北京之旅", "trip_json": SAMPLE_TRIP})
        assert resp.status_code == 200
        trip_id = resp.json()["id"]
        # 列表
        resp = c.get("/api/trips")
        assert resp.status_code == 200
        trips = resp.json()["trips"]
        assert trips[0]["id"] == trip_id
        assert trips[0]["title"] == "北京之旅"
        assert trips[0]["days"] == 1
        # 详情
        resp = c.get(f"/api/trips/{trip_id}")
        assert resp.status_code == 200
        assert resp.json()["trip_json"] == SAMPLE_TRIP
        # 删除
        resp = c.delete(f"/api/trips/{trip_id}")
        assert resp.status_code == 200
        assert c.get(f"/api/trips/{trip_id}").status_code == 404


def test_api_trips_errors(tmp_db):
    with TestClient(app) as c:
        assert c.get("/api/trips/nope").status_code == 404
        assert c.delete("/api/trips/nope").status_code == 404


def test_api_trips_default_title(tmp_db):
    with TestClient(app) as c:
        resp = c.post("/api/trips", json={"title": "  ", "trip_json": SAMPLE_TRIP})
        assert resp.status_code == 200
        assert resp.json()["title"] == "我的行程"
