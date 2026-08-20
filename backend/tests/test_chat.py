import pytest
from fastapi.testclient import TestClient

from app import db
from app.graph import build_graph as _real_build_graph
from app.main import app

from conftest import FakeProvider
from test_researcher import _kwargs as _researcher_kwargs


class ReplanFakeProvider(FakeProvider):
    """第二轮"行程规划JSON"按修改语义返回新行程（模拟真实 LLM 重排）。

    brief 原设计的 fake 两轮都返回同一 canned ITINERARY，而 planner 节点对
    确定性输入输出确定性回复 → 两轮回复逐字节相同，"非旧回复"断言无法成立
    （已实证）。spec 测试策略要求"第二轮 fake 按修改语义响应"，由本子类实现：
    第二次命中"行程规划JSON"时返回博物馆行程。json_responses 的 5 键与
    brief 一字不改。
    """

    def __init__(self, json_responses=None, text_responses=None) -> None:
        super().__init__(json_responses, text_responses)
        self._itinerary_rounds = 0

    def chat_json(self, messages: list[dict]) -> dict:
        resp = super().chat_json(messages)
        if "行程规划JSON" in messages[-1]["content"]:
            self._itinerary_rounds += 1
            if self._itinerary_rounds == 2:
                itinerary = dict(resp)
                days = []
                for day in itinerary.get("days") or []:
                    day = dict(day)
                    day["title"] = "博物馆日"
                    day["items"] = [{"time": "14:00", "name": "广州博物馆", "note": "按修改要求"}]
                    days.append(day)
                itinerary["days"] = days
                return itinerary
        return resp


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
    fake = ReplanFakeProvider(
        json_responses={
            "已有画像": {
                "destination": "广州", "duration_days": 3, "start_date": None,
                "budget_cny": 8000, "travelers": 2, "preferences": ["美食"],
                "missing": [],
            },
            "推荐要点JSON": {"recommendations": [{"poi_id": "guangzhou-001", "reason": "夜景绝佳"}]},
            "预算分配JSON": {"items": [{"category": "住宿", "amount": 3200, "note": "中档酒店"}],
                            "total": 8000},
            "行程规划JSON": ITINERARY,
            "汇总JSON": {"summary": "整体节奏合理。", "tips": ["周三起降温"]},
        }
    )
    app.state.graph = None
    app.state.llm_configured = False
    # lifespan 用 get_provider 构建 provider（chat.py 每请求再 build 带 checkpointer 的图）
    def _fake_provider():
        return fake
    monkeypatch.setattr("app.main.get_provider", _fake_provider)
    # researcher 依赖注入：chat.py 的 build_graph 注入 fake weather/search/normalize，
    # 测试全 mock 无网络（真实实现依赖 Open-Meteo 网络与 chroma 数据，违反全 mock 约束）
    def _fake_graph(provider, *, checkpointer=None):
        return _real_build_graph(provider, checkpointer=checkpointer, **_researcher_kwargs())

    monkeypatch.setattr("app.api.chat.build_graph", _fake_graph)
    with TestClient(app) as c:
        yield c
    app.state.graph = None
    app.state.llm_configured = False


def test_chat_returns_reply_and_persists(client):
    resp = client.post("/api/chat", json={"message": "10月去广州玩3天预算8000"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"]
    assert data["reply"].startswith("## ")
    msgs = db.list_messages(data["session_id"])
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[-1]["content"] == data["reply"]


def test_chat_continues_session(client):
    r1 = client.post("/api/chat", json={"message": "10月去广州玩3天预算8000"}).json()
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


def test_chat_second_round_keeps_profile(client):
    """checkpointer 延续画像：第二轮 analyst 提示词含旧画像，回复为第二轮行程。"""
    r1 = client.post("/api/chat", json={"message": "10月去广州玩3天预算8000"}).json()
    r2 = client.post("/api/chat", json={"session_id": r1["session_id"], "message": "第二天换成博物馆"})
    assert r2.status_code == 200
    assert r2.json()["session_id"] == r1["session_id"]
    assert r2.json()["reply"].startswith("## ")
    # 全部 fake LLM 调用中，analyst（含"已有画像"的提示词）最后一次应带旧画像
    analyst_prompts = [c for c in client.app.state.provider.calls if "已有画像" in c[-1]["content"]]
    assert len(analyst_prompts) == 2
    assert "广州" in analyst_prompts[-1][-1]["content"]
    assert "8000" in analyst_prompts[-1][-1]["content"]


def test_chat_replan_produces_new_reply(client):
    """第二轮全量重排：回复为第二轮行程（新 itinerary），非旧回复。"""
    r1 = client.post("/api/chat", json={"message": "10月去广州玩3天预算8000"}).json()
    r2 = client.post("/api/chat", json={"session_id": r1["session_id"], "message": "第二天换成博物馆"})
    assert r2.json()["reply"] != r1["reply"]


def test_chat_unknown_session_creates_new(client):
    """非法 session_id → 后端按新会话处理（不崩溃）。"""
    resp = client.post("/api/chat", json={"session_id": "deadbeef", "message": "10月去广州玩3天预算8000"})
    assert resp.status_code == 200
    assert resp.json()["session_id"] != "deadbeef"


def test_history_returns_messages_in_order(client):
    """GET /api/chat/history：两次 chat 后返回 4 条消息，role 按 user/assistant 交替且升序。"""
    r1 = client.post("/api/chat", json={"message": "10月去广州玩3天预算8000"}).json()
    sid = r1["session_id"]
    r2_resp = client.post("/api/chat", json={"session_id": sid, "message": "第二天换成博物馆"})
    assert r2_resp.status_code == 200
    r2 = r2_resp.json()
    resp = client.get(f"/api/chat/history?session_id={sid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == sid
    msgs = body["messages"]
    assert len(msgs) == 4
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    # 升序：首条 = 第 1 轮 user 消息，末条 = 第 2 轮 assistant 回复
    assert msgs[0]["content"] == "10月去广州玩3天预算8000"
    assert msgs[-1]["content"] == r2["reply"]


def test_history_unknown_session_returns_404(client):
    resp = client.get("/api/chat/history?session_id=deadbeef")
    assert resp.status_code == 404
