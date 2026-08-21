import json

from app.agents import planner

from conftest import FakeProvider

CANDIDATES = [
    {"poi_id": "guangzhou-001", "province": "广东", "city": "广州", "name": "广州塔",
     "category": "attraction", "lat": 23.1066, "lng": 113.3245, "rating": 4.6,
     "price_tier": 3, "description": "珠江畔地标。", "tags": ["夜景"], "reason": "夜景绝佳"},
    {"poi_id": "guangzhou-002", "province": "广东", "city": "广州", "name": "白云山",
     "category": "attraction", "lat": 23.18, "lng": 113.29, "rating": 4.4,
     "price_tier": 1, "description": "城市绿肺。", "tags": ["自然"], "reason": ""},
]

ITINERARY = {
    "days": [{"day": 1, "title": "广州地标", "weather_note": "晴 24°C",
              "items": [{"time": "19:00", "name": "广州塔", "poi_id": "guangzhou-001", "note": "夜景"},
                        {"time": "12:30", "name": "点都德（示例）", "note": "午餐"}]}],
    "summary": "OK", "warnings": [],
}

BUDGET_PLAN = {
    "items": [{"category": "住宿", "amount": 3200, "note": "中档酒店"},
              {"category": "餐饮", "amount": 2400, "note": "粤菜"}],
    "total": 8000, "checked": True, "scaled": False,
}

WEATHER = [{"date": "2026-10-01", "t_max": 24.0, "t_min": 16.0, "condition": "晴", "source": "open-meteo"}]


def _fake():
    return FakeProvider(json_responses={"行程": ITINERARY})


def _state():
    return {
        "messages": [{"role": "user", "content": "10月去广州玩3天，预算8000，喜欢美食"}],
        "phase": "planning",
        "profile": {"destination": "广州", "duration_days": 3, "start_date": "2026-10-01",
                    "budget_cny": 8000, "travelers": 2, "preferences": ["美食"]},
        "candidates": CANDIDATES, "budget_plan": BUDGET_PLAN, "weather": WEATHER,
        "region_resolved": True,
    }


def test_planner_produces_reply_and_itinerary():
    fake = _fake()
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert out["phase"] == "answered"
    assert out["itinerary"]["days"][0]["items"][0]["poi_id"] == "guangzhou-001"
    assert out["last_reply"].startswith("## ")


def test_planner_prompt_contains_candidates_budget_weather():
    fake = _fake()
    planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    prompt = fake.calls[0][-1]["content"]
    assert "广州塔" in prompt and "白云山" in prompt     # 候选进上下文
    assert "夜景绝佳" in prompt                          # 推荐理由进上下文
    assert "3200" in prompt                              # 预算约束进上下文
    assert "晴" in prompt                                # 天气进上下文


def test_planner_unknown_region_returns_hint():
    fake = _fake()
    state = _state()
    state["region_resolved"] = False
    state["profile"]["destination"] = "巴黎"
    out = planner.planner_node(state, fake)  # type: ignore[arg-type]
    assert out["phase"] == "answered"
    assert "巴黎" in out["last_reply"]
    assert "暂不支持" in out["last_reply"]
    assert "可尝试输入所在省份名" in out["last_reply"]  # 提示改用省份名
    assert fake.calls == []  # 未知目的地不调用 LLM


def test_planner_empty_candidates_degrades_without_llm():
    """KB 为空/未入库：region_resolved=True 但 candidates=[] → 降级提示，不调用 LLM。"""
    fake = _fake()
    state = _state()
    state["candidates"] = []
    out = planner.planner_node(state, fake)  # type: ignore[arg-type]
    assert out["phase"] == "answered"
    assert "该区域暂未检索到景点数据" in out["last_reply"]
    assert "python -m app.rag.generate" in out["last_reply"]
    assert "python -m app.rag.ingest" in out["last_reply"]
    assert fake.calls == []  # 空候选不调用 LLM（防编造景点渲染成真实行程）


def test_planner_filters_hallucinated_poi():
    """有 poi_id 但不在候选 → 编造景点丢弃；零引用兜底注入后仅剩 top 候选条目。"""
    hallucinated = {
        "days": [{"day": 1, "title": "x", "weather_note": "晴",
                  "items": [{"time": "09:00", "name": "编造的景点", "poi_id": "nope-999", "note": ""}]}],
        "summary": "x", "warnings": [],
    }
    fake = FakeProvider(json_responses={"行程规划JSON": hallucinated,
                                        "上一版行程没有引用": hallucinated})
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    items = out["itinerary"]["days"][0]["items"]
    assert [i["name"] for i in items] == ["广州塔"]  # 编造的景点被丢弃，只剩注入的 top 候选


def test_planner_keeps_example_food_without_poi_id():
    """无 poi_id 的条目（LLM 生成的示例餐饮/住宿）保留（注入条目前置、示例条目仍在）。"""
    zero_ref = {
        "days": [{"day": 1, "title": "x", "weather_note": "晴",
                  "items": [{"time": "12:30", "name": "点都德（示例）", "note": "午餐"}]}],
        "summary": "x", "warnings": [],
    }
    fake = FakeProvider(json_responses={"行程规划JSON": zero_ref,
                                        "上一版行程没有引用": zero_ref})
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    items = out["itinerary"]["days"][0]["items"]
    assert items[0]["poi_id"] == "guangzhou-001"                     # 注入的 top 候选
    assert items[1]["name"] == "点都德（示例）" and "poi_id" not in items[1]  # 示例条目保留


def test_planner_days_null_tolerated():
    fake = FakeProvider(json_responses={"行程规划JSON": {"days": None, "summary": "无行程。", "warnings": []}})
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert out["phase"] == "answered"
    assert "行程总结" in out["last_reply"]


def test_format_itinerary_shape():
    text = planner.format_itinerary(ITINERARY)
    assert "第 1 天" in text and "广州塔" in text and "## " in text


def test_planner_enriches_itinerary_with_candidate_coords():
    fake = _fake()
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    item = out["itinerary"]["days"][0]["items"][0]
    assert item["poi_id"] == "guangzhou-001"
    assert item["lat"] == 23.1066 and item["lng"] == 113.3245
    food = out["itinerary"]["days"][0]["items"][1]
    assert "lat" not in food  # 示例餐饮无坐标，不上地图


def test_planner_publishes_itinerary_update(monkeypatch):
    published: list[dict] = []
    monkeypatch.setattr("app.agents.planner.events.publish", lambda p: published.append(p))
    fake = _fake()
    planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    updates = [p for p in published if p["type"] == "itinerary_update"]
    assert len(updates) == 1
    assert updates[0]["data"]["status"] == "generated"
    assert updates[0]["data"]["itinerary"]["days"][0]["items"][0]["lat"] == 23.1066


def test_planner_llm_failure_returns_summary_reply_without_event(monkeypatch):
    """LLM 异常（chat_json 抛错 → itinerary={}）→ days-None 降级回复，且不发布空行程事件。"""
    published: list[dict] = []
    monkeypatch.setattr("app.agents.planner.events.publish", lambda p: published.append(p))
    out = planner.planner_node(_state(), FakeProvider())  # type: ignore[arg-type]
    assert out["last_reply"] == "行程总结："  # 降级分支存活（T8-F4 回归）
    assert not [p for p in published if p["type"] == "itinerary_update"]


def test_planner_retries_once_when_zero_candidate_reference():
    """零引用（地图空图）→ 追加纠正指令重试一次，第二次引用候选 → 行程含引用。"""
    fake = FakeProvider(json_responses={
        "行程规划JSON": {"days": [{"day": 1, "title": "x", "weather_note": "晴",
                                   "items": [{"time": "12:30", "name": "点都德（示例）", "note": "午餐"}]}],
                         "summary": "x", "warnings": []},
        "上一版行程没有引用": {"days": [{"day": 1, "title": "x", "weather_note": "晴",
                                         "items": [{"time": "09:00", "name": "广州塔", "poi_id": "guangzhou-001", "note": ""}]}],
                               "summary": "x", "warnings": []},
    })
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert len(fake.calls) == 2  # 重试了一次
    assert "上一版行程没有引用" in fake.calls[-1][-1]["content"]  # 纠正指令送达
    item = out["itinerary"]["days"][0]["items"][0]
    assert item["poi_id"] == "guangzhou-001"
    assert item["lat"] == 23.1066  # 富化正常（现有集成）


def test_planner_zero_reference_twice_still_terminates():
    """两轮都零引用 → 不再重试，注入 top 候选兜底，正常格式化（不无限循环）。"""
    zero_ref = {"days": [{"day": 1, "title": "x", "weather_note": "晴",
                          "items": [{"time": "12:30", "name": "点都德（示例）", "note": "午餐"}]}],
                "summary": "x", "warnings": []}
    fake = FakeProvider(json_responses={"行程规划JSON": zero_ref,
                                        "上一版行程没有引用": zero_ref})
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert len(fake.calls) == 2
    assert out["last_reply"].startswith("## ")


def test_planner_llm_exception_no_retry():
    """LLM 异常 → 不重试，走 days-None 降级。"""
    fake = FakeProvider()  # 无响应配置 → chat_json 抛 AssertionError
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert len(fake.calls) == 1
    assert out["last_reply"] == "行程总结："


def test_planner_prompt_requires_candidate_reference():
    assert "每天必须至少安排 1-2 个候选景点并引用其 poi_id" in planner.PLANNER_SYSTEM_PROMPT


def test_planner_injects_top_candidate_after_two_zero_reference_rounds():
    """两轮 LLM 零引用 → 确定性注入 top-1 候选（带坐标，地图必有点）。"""
    zero_ref = {"days": [{"day": 1, "title": "x", "weather_note": "晴",
                          "items": [{"time": "12:30", "name": "点都德（示例）", "note": "午餐"}]}],
                "summary": "x", "warnings": []}
    fake = FakeProvider(json_responses={"行程规划JSON": zero_ref,
                                        "上一版行程没有引用": zero_ref})
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert len(fake.calls) == 2  # 重试照常
    item = out["itinerary"]["days"][0]["items"][0]
    assert item["poi_id"] == "guangzhou-001"  # CANDIDATES[0]（广州塔）
    assert item["name"] == "广州塔"
    assert item["note"] == "推荐安排"
    assert item["lat"] == 23.1066  # 富化正常
