from app import events
from app.graph import build_graph

from conftest import FakeProvider
from test_researcher import _kwargs as _researcher_kwargs  # fake weather/search/normalize
from test_planner import CANDIDATES  # 复用候选常量


def _fake() -> FakeProvider:
    return FakeProvider(json_responses={
        "已有画像": {
            "destination": "广州", "duration_days": 3, "start_date": None,
            "budget_cny": 8000, "travelers": 2, "preferences": ["美食"], "missing": [],
        },
        "推荐要点JSON": {"recommendations": [{"poi_id": "guangzhou-001", "reason": "夜景绝佳"}]},
        "预算分配JSON": {"items": [{"category": "住宿", "amount": 3200, "note": "中档酒店"}],
                        "total": 8000},
        "行程规划JSON": {"days": [{"day": 1, "title": "广州地标", "weather_note": "晴",
                                  "items": [{"time": "19:00", "name": "广州塔", "poi_id": "guangzhou-001", "note": ""}]}],
                        "summary": "OK", "warnings": []},
        "汇总JSON": {"summary": "整体节奏合理。", "tips": ["周三起降温"]},
    })


def test_full_planning_flow():
    graph = build_graph(_fake(), **_researcher_kwargs())  # type: ignore[arg-type]
    result = graph.invoke({
        "messages": [{"role": "user", "content": "10月去广州玩3天，预算8000，喜欢美食"}],
        "phase": "",
    })
    assert result["phase"] == "answered"
    assert result["itinerary"]["days"][0]["items"][0]["poi_id"] == "guangzhou-001"
    assert result["budget_plan"]["checked"] is True
    assert result["supervisor_summary"]["summary"] == "整体节奏合理。"
    assert result["last_reply"].startswith("## ")
    assert "## 预算分配" in result["last_reply"]


def test_incomplete_request_ends_at_analyst():
    fake = FakeProvider(json_responses={"最新需求": {
        "destination": None, "duration_days": 3, "start_date": None,
        "budget_cny": None, "travelers": 1, "preferences": [],
        "missing": ["destination"],
    }})
    graph = build_graph(fake, **_researcher_kwargs())  # type: ignore[arg-type]
    result = graph.invoke({
        "messages": [{"role": "user", "content": "帮我规划3天"}],
        "phase": "",
    })
    assert result["phase"] == "asking"
    assert "想去哪个城市" in result["messages"][-1]["content"]


def test_unknown_region_ends_with_hint_without_supervisor():
    """未知目的地 → researcher 置 region_resolved=False → planner 输出降级回复后直接 END，
    supervisor 不运行（防止空行程覆盖降级回复），不调用 LLM。"""
    fake = FakeProvider(json_responses={"已有画像": {
        "destination": "巴黎", "duration_days": 3, "start_date": None,
        "budget_cny": 8000, "travelers": 2, "preferences": [], "missing": [],
    }})
    graph = build_graph(fake, **_researcher_kwargs())  # type: ignore[arg-type]
    result = graph.invoke({
        "messages": [{"role": "user", "content": "10月去巴黎玩3天，预算8000"}],
        "phase": "",
    })
    assert result["phase"] == "answered"
    assert "暂不支持" in result["last_reply"] and "巴黎" in result["last_reply"]
    # budget 在并行 fan-out 中与 researcher 同时执行（不依赖 candidates），照常调用 LLM 一次；
    # researcher 早退、planner 走降级分支、supervisor 不运行 → 共 analyst + budget 2 次
    assert len(fake.calls) == 2


def test_empty_candidates_ends_with_planner_degrade_without_supervisor():
    """KB 空/未入库：researcher 归一化成功但 candidates=[] → planner 降级回复后直接 END，
    supervisor 不运行（防覆盖降级回复），planner/supervisor 均不调用 LLM。"""
    fake = FakeProvider(json_responses={
        "已有画像": {
            "destination": "河北", "duration_days": 3, "start_date": None,
            "budget_cny": 8000, "travelers": 2, "preferences": [], "missing": [],
        },
        "预算分配JSON": {"items": [{"category": "住宿", "amount": 3200, "note": "中档酒店"}],
                        "total": 8000},
    })
    kwargs = _researcher_kwargs()  # search_pois_fn 仅"广州"返回候选 → 河北返回 []

    def normalize(name):
        return ("河北", None) if "河北" in name else (None, None)

    kwargs["normalize_region_fn"] = normalize  # 区域归一化成功、候选为空
    graph = build_graph(fake, **kwargs)  # type: ignore[arg-type]
    result = graph.invoke({
        "messages": [{"role": "user", "content": "10月去河北玩3天，预算8000"}],
        "phase": "",
    })
    assert result["phase"] == "answered"
    assert "该区域暂未检索到景点数据" in result["last_reply"]
    # planner 降级分支与 supervisor 均未调用 LLM：仅 analyst + budget 共 2 次
    assert len(fake.calls) == 2
    assert not any("行程规划JSON" in c[-1]["content"] for c in fake.calls)
    assert not any("汇总JSON" in c[-1]["content"] for c in fake.calls)


def test_nodes_publish_agent_status():
    q = events.subscribe()
    try:
        graph = build_graph(_fake(), **_researcher_kwargs())  # type: ignore[arg-type]
        graph.invoke({
            "messages": [{"role": "user", "content": "10月去广州玩3天，预算8000，喜欢美食"}],
            "phase": "",
        })
        seen = []
        while not q.empty():
            ev = q.get_nowait()
            if ev["type"] == "agent_status":
                seen.append((ev["data"]["agent"], ev["data"]["status"]))
    finally:
        events.unsubscribe(q)
    by_agent: dict[str, list[str]] = {}
    for agent, status in seen:
        by_agent.setdefault(agent, []).append(status)
    for agent in ("analyst", "researcher", "budget", "planner", "supervisor"):
        assert by_agent.get(agent) == ["start", "done"], f"{agent}: {by_agent.get(agent)}"
