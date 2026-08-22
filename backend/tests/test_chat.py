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
    第二次命中"行程规划JSON"时返回博物馆行程。json_responses 在 brief 的 5 键
    基础上加 "最新需求" 键并置于最前：analyst prompt 同时含 "已有画像" 与
    "最新需求" 两子串，FakeProvider 按插入序匹配，追问轮测试覆盖 "最新需求"
    值时必须优先命中（否则 "已有画像" 的完整画像先匹配，追问轮会误跑全流程）。
    """

    def __init__(self, json_responses=None, text_responses=None) -> None:
        super().__init__(json_responses, text_responses)
        self._itinerary_rounds = 0

    def chat_json(self, messages: list[dict]) -> dict:
        if "上一版行程没有引用" in messages[-1]["content"]:
            # planner 零引用兜底的重试轮：返回带 poi_id 引用的博物馆行程
            # （无引用会触发纠正重试；本 fake 未配置纠正响应则抛错降级，回复不满足断言）
            self.calls.append(messages)
            base = self.json_responses["行程规划JSON"]
            return {
                "days": [{"day": 1, "title": "博物馆日", "weather_note": "晴",
                          "items": [{"name": "广州博物馆", "poi_id": "guangzhou-001",
                                     "suggested_time": "建议上午 9:00-11:00 前往",
                                     "time_reason": "馆内人少、观展从容", "note": "按修改要求"}]}],
                "summary": base.get("summary"),
                "warnings": list(base.get("warnings", [])),
            }
        resp = super().chat_json(messages)
        if "行程规划JSON" in messages[-1]["content"]:
            self._itinerary_rounds += 1
            if self._itinerary_rounds == 2:
                itinerary = dict(resp)
                days = []
                for day in itinerary.get("days") or []:
                    day = dict(day)
                    day["title"] = "博物馆日"
                    day["items"] = [{"name": "广州博物馆", "note": "按修改要求"}]
                    days.append(day)
                itinerary["days"] = days
                return itinerary
        return resp


ITINERARY = {
    "days": [{"day": 1, "title": "广州地标", "weather_note": "晴",
              "items": [{"name": "广州塔", "poi_id": "guangzhou-001",
                         "suggested_time": "建议晚上 19:00 后前往", "time_reason": "夜景绝佳",
                         "note": "夜景",
                         "detail": "广州塔高600米，昵称小蛮腰，登顶可俯瞰珠江新城全景。"}]}],
    "accommodation": [{"name": "锦江宾馆（示例）", "days": [1, 2],
                       "location_note": "锦江区，近春熙路",
                       "commute_note": "到当日景点约 15-30 分钟车程",
                       "price_note": "中档，符合预算",
                       "detail": "大堂现代、带健身房与自助早餐"}],
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
            "最新需求": {
                "destination": "广州", "duration_days": 3, "start_date": None,
                "budget_cny": 8000, "travelers": 2, "preferences": ["美食"],
                "missing": [],
            },
            "已有画像": {
                "destination": "广州", "duration_days": 3, "start_date": None,
                "budget_cny": 8000, "travelers": 2, "preferences": ["美食"],
                "missing": [],
            },
            "推荐要点JSON": {"recommendations": [{"poi_id": "guangzhou-001", "reason": "夜景绝佳"}]},
            "预算分配JSON": {"items": [
                {"category": "住宿", "amount": 3200, "note": "中档酒店"},
                {"category": "交通", "amount": 1600, "note": "高铁往返"},
                {"category": "餐饮", "amount": 2000, "note": "粤菜尝鲜"},
                {"category": "门票", "amount": 800, "note": "景点联票"},
                {"category": "其他", "amount": 400, "note": "机动余量"},
            ], "total": 8000},
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


def test_chat_response_includes_trip(client):
    r = client.post("/api/chat", json={"message": "10月去广州玩3天预算8000"}).json()
    trip = r["trip"]
    assert trip is not None
    item = trip["itinerary"]["days"][0]["items"][0]
    assert item["poi_id"] == "guangzhou-001"
    assert item["lat"] == 23.1066 and item["lng"] == 113.3245  # 富化坐标
    assert trip["budget_plan"]["total"] == 8000
    assert trip["summary"] == "整体节奏合理。"
    assert trip["tips"] == ["周三起降温"]


def test_chat_asking_round_trip_is_null(client):
    """追问轮（画像不完整 → analyst 追问后 END）→ trip 为 null。"""
    client.app.state.provider.json_responses["最新需求"] = {
        "destination": None, "duration_days": 3, "start_date": None,
        "budget_cny": 8000, "travelers": 2, "preferences": ["美食"],
        "missing": ["destination"],
    }
    r = client.post("/api/chat", json={"message": "帮我规划3天"}).json()
    assert r["trip"] is None
    assert "想去哪个城市" in r["reply"]


def test_chat_asking_after_completed_trip_returns_null_trip(client):
    """已完成行程的会话上发生追问轮（checkpointer 恢复旧 itinerary）→ trip 仍为 null。

    回归：追问轮 analyst 只返回 phase=asking，不覆盖 itinerary；checkpointer 恢复
    上一轮的旧 itinerary 后，_build_trip 若只看 itinerary 有无 days，会把旧行程
    当作本轮 trip 返回 → 前端把追问消息渲染成旧地图 TripView（违反 trip:null 契约）。
    """
    r1 = client.post("/api/chat", json={"message": "10月去广州玩3天预算8000"}).json()
    assert r1["trip"] is not None  # 前置：第一轮已完成并落库行程
    client.app.state.provider.json_responses["最新需求"] = {
        "destination": None, "duration_days": 3, "start_date": None,
        "budget_cny": 8000, "travelers": 2, "preferences": ["美食"],
        "missing": ["destination"],
    }
    resp = client.post("/api/chat", json={
        "session_id": r1["session_id"], "message": "预算能再压一点吗",
    })
    assert resp.status_code == 200
    r2 = resp.json()
    assert "想去哪个城市" in r2["reply"]  # 确为追问轮（非重跑全流程）
    assert r2["trip"] is None


def test_itinerary_endpoint_returns_latest_trip(client):
    r1 = client.post("/api/chat", json={"message": "10月去广州玩3天预算8000"}).json()
    r2 = client.post("/api/chat", json={"session_id": r1["session_id"], "message": "第二天换成博物馆"}).json()
    resp = client.get(f"/api/itinerary?session_id={r1['session_id']}")
    assert resp.status_code == 200
    assert resp.json()["trip"]["itinerary"] == r2["trip"]["itinerary"]  # 最新行程（重排后）


def test_itinerary_endpoint_unknown_session_404(client):
    resp = client.get("/api/itinerary?session_id=deadbeef")
    assert resp.status_code == 404


def test_itinerary_endpoint_session_without_trip_404(client):
    """追问轮会话从未产出行程 → 404（前端静默回退文本渲染）。"""
    client.app.state.provider.json_responses["最新需求"] = {
        "destination": None, "duration_days": 3, "start_date": None,
        "budget_cny": 8000, "travelers": 2, "preferences": [],
        "missing": ["destination"],
    }
    r = client.post("/api/chat", json={"message": "帮我规划"}).json()
    resp = client.get(f"/api/itinerary?session_id={r['session_id']}")
    assert resp.status_code == 404
