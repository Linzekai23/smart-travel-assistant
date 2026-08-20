from app import events
from app.graph import build_graph

from conftest import FakeProvider
from test_planner import _kwargs  # 复用 Task 8 的假检索器注入（含 weather_fn）

ITINERARY = {
    "days": [{"day": 1, "title": "熊猫基地", "weather_note": "晴",
              "items": [{"time": "09:00", "name": "宽窄巷子", "poi_id": "chengdu-001", "note": ""}]}],
    "summary": "OK", "warnings": [],
}


def _fake() -> FakeProvider:
    return FakeProvider(
        json_responses={
            "已有画像": {
                "destination": "成都", "duration_days": 1, "start_date": None,
                "budget_cny": 8000, "travelers": 2, "preferences": ["美食"],
                "missing": [],
            },
            "行程": ITINERARY,
        }
    )


def test_full_planning_flow():
    graph = build_graph(_fake(), **_kwargs())  # type: ignore[arg-type]
    result = graph.invoke({
        "messages": [{"role": "user", "content": "10月去成都玩3天，预算8000"}],
        "phase": "",
    })
    assert result["phase"] == "answered"
    assert result["itinerary"]["days"][0]["items"][0]["poi_id"] == "chengdu-001"
    assert result["last_reply"].startswith("## ")


def test_incomplete_request_ends_at_analyst():
    fake = FakeProvider(json_responses={"最新需求": {
        "destination": None, "duration_days": 3, "start_date": None,
        "budget_cny": None, "travelers": 1, "preferences": [],
        "missing": ["destination"],
    }})
    graph = build_graph(fake, **_kwargs())  # type: ignore[arg-type]
    result = graph.invoke({
        "messages": [{"role": "user", "content": "帮我规划3天"}],
        "phase": "",
    })
    assert result["phase"] == "asking"
    assert "想去哪个城市" in result["messages"][-1]["content"]


def test_nodes_publish_agent_status():
    q = events.subscribe()
    try:
        graph = build_graph(_fake(), **_kwargs())  # type: ignore[arg-type]
        graph.invoke({
            "messages": [{"role": "user", "content": "10月去成都玩3天，预算8000"}],
            "phase": "",
        })
        seen = []
        while not q.empty():
            ev = q.get_nowait()
            if ev["type"] == "agent_status":
                seen.append((ev["data"]["agent"], ev["data"]["status"]))
    finally:
        events.unsubscribe(q)
    by_agent = {"analyst": [], "planner": []}
    for agent, status in seen:
        by_agent[agent].append(status)
    assert "start" in by_agent["analyst"] and "done" in by_agent["analyst"]
    assert "start" in by_agent["planner"] and "done" in by_agent["planner"]
