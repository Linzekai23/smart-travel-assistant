import pytest
from fastapi.testclient import TestClient

from app import db
from app.graph import build_graph
from app.main import app

from conftest import FakeProvider, fake_weather
from test_planner import _kwargs

ITINERARY = {
    "days": [{"day": 1, "title": "熊猫基地", "weather_note": "晴",
              "items": [{"time": "09:00", "name": "宽窄巷子", "poi_id": "chengdu-001", "note": ""}]}],
    "summary": "OK", "warnings": [],
}


@pytest.fixture(autouse=True)
def _no_real_provider(monkeypatch):
    """本模块所有用例强制 lifespan 走"未配置"分支。

    starlette 1.6 的 TestClient 总是执行 lifespan（lifespan="off" 参数已移除），
    且本机可能已配置 DEEPSEEK_API_KEY；不接管 get_provider 的话 lifespan 会
    构建真实 Provider/图，导致用例依赖环境甚至联网。
    """

    def _raise() -> None:
        raise RuntimeError("缺少环境变量 DEEPSEEK_API_KEY（DeepSeek 平台申请后配置）")

    monkeypatch.setattr("app.main.get_provider", _raise)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAVEL_DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    fake = FakeProvider(
        json_responses={
            "已有画像": {
                "destination": "成都", "duration_days": 1, "start_date": None,
                "budget_cny": 8000, "travelers": 2, "preferences": [],
                "missing": [],
            },
            "行程": ITINERARY,
        }
    )
    app.state.graph = None
    app.state.llm_configured = False
    # starlette 1.6 无 lifespan="off" 参数，TestClient 总是先执行 lifespan
    # （lifespan 会把 graph 重置为 None），因此进入上下文后再注入假图。
    with TestClient(app) as c:
        app.state.graph = build_graph(fake, **_kwargs())  # type: ignore[arg-type]
        app.state.llm_configured = True
        yield c
    app.state.graph = None
    app.state.llm_configured = False


def test_chat_returns_reply_and_persists(client):
    resp = client.post("/api/chat", json={"message": "10月去成都玩3天预算8000"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"]
    assert data["reply"].startswith("## ")
    msgs = db.list_messages(data["session_id"])
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[-1]["content"] == data["reply"]


def test_chat_continues_session(client):
    r1 = client.post("/api/chat", json={"message": "10月去成都玩3天预算8000"}).json()
    r2 = client.post("/api/chat", json={"session_id": r1["session_id"], "message": "第二天换成博物馆"})
    assert r2.status_code == 200
    msgs = db.list_messages(r1["session_id"])
    assert len(msgs) == 4


def test_chat_without_llm_returns_503(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAVEL_DB_PATH", str(tmp_path / "nokey.db"))
    db.init_db()
    app.state.graph = None
    app.state.llm_configured = False
    with TestClient(app) as c:
        resp = c.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 503
    assert "DEEPSEEK_API_KEY" in resp.json()["detail"]
    app.state.graph = None
    app.state.llm_configured = False


def test_chat_empty_message_returns_422(client):
    resp = client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 422
