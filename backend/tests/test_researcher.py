from app.agents import researcher

from conftest import FakeProvider, fake_weather

CANDIDATES = [
    {"poi_id": "guangzhou-001", "province": "广东", "city": "广州", "name": "广州塔",
     "category": "attraction", "lat": 23.1066, "lng": 113.3245, "rating": 4.6,
     "price_tier": 3, "description": "珠江畔地标。", "tags": ["夜景"]},
    {"poi_id": "guangzhou-002", "province": "广东", "city": "广州", "name": "白云山",
     "category": "attraction", "lat": 23.18, "lng": 113.29, "rating": 4.4,
     "price_tier": 1, "description": "城市绿肺。", "tags": ["自然"]},
]


def _fake():
    return FakeProvider(json_responses={"推荐要点JSON": {
        "recommendations": [
            {"poi_id": "guangzhou-001", "reason": "夜景绝佳，适合晚上登塔"},
        ],
    }})


def _state():
    return {
        "messages": [{"role": "user", "content": "10月去广州玩3天，预算8000，喜欢美食"}],
        "phase": "planning",
        "profile": {"destination": "广州", "duration_days": 3, "start_date": "2026-10-01",
                    "budget_cny": 8000, "travelers": 2, "preferences": ["美食"]},
    }


def _normalize(name):
    return ("广东", "广州") if "广州" in name else (None, None)


def _search(name, *, query=None, k=8):
    return list(CANDIDATES) if "广州" in name else []


def _kwargs():
    return {"weather_fn": fake_weather, "search_pois_fn": _search, "normalize_region_fn": _normalize}


def test_researcher_candidates_weather_reason():
    fake = _fake()
    out = researcher.researcher_node(_state(), fake, **_kwargs())  # type: ignore[arg-type]
    assert out["region_resolved"] is True
    assert [p["poi_id"] for p in out["candidates"]] == ["guangzhou-001", "guangzhou-002"]
    assert out["candidates"][0]["reason"] == "夜景绝佳，适合晚上登塔"
    assert out["candidates"][1]["reason"] == ""  # 未推荐 → 空理由
    assert out["weather"] and out["weather"][0]["source"] == "open-meteo"


def test_researcher_unknown_region():
    state = _state()
    state["profile"]["destination"] = "未知名胜"
    out = researcher.researcher_node(state, FakeProvider(), **_kwargs())  # type: ignore[arg-type]
    assert out["region_resolved"] is False
    assert out["candidates"] == [] and out["weather"] == []


def test_researcher_prompt_contains_candidates():
    fake = _fake()
    researcher.researcher_node(_state(), fake, **_kwargs())  # type: ignore[arg-type]
    prompt = fake.calls[0][-1]["content"]
    assert "广州塔" in prompt and "poi_id" in prompt


def test_researcher_no_candidates_uses_province_capital():
    """已解析区域但候选为空 → 天气锚定省会（city_coord(province, None)），不崩溃。"""
    state = _state()
    state["profile"]["destination"] = "河北"

    def normalize(name):
        if "河北" in name:
            return ("河北", None)
        return _normalize(name)

    out = researcher.researcher_node(
        state, FakeProvider(), weather_fn=fake_weather,
        search_pois_fn=_search, normalize_region_fn=normalize,
    )  # type: ignore[arg-type]
    assert out["region_resolved"] is True
    assert out["candidates"] == []
    assert out["weather"] and out["weather"][0]["source"] == "open-meteo"
