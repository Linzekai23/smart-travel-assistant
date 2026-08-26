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
    # search_attractions_fn 默认返回 [] → 现有测试全部留在 RAG 路径
    # （防本机 AMAP_KEY 使旧用例走真实高德 HTTP）
    return {"weather_fn": fake_weather, "search_pois_fn": _search,
            "normalize_region_fn": _normalize, "search_attractions_fn": lambda city: []}


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


# ---- 高德景点优先 + RAG 兜底 ----

AMAP_ATTRACTIONS = [
    {"poi_id": "amap-B000A1", "name": "成都塔", "city": "成都", "category": "attraction",
     "lat": 30.64, "lng": 104.05, "address": "锦江区", "tel": "028-1234567",
     "photo_url": "https://amap.example/photo1.jpg"},
    {"poi_id": "amap-B000A2", "name": "锦里古街", "city": "成都", "category": "attraction",
     "lat": 30.648, "lng": 104.049, "address": "武侯区"},
]


def _amap_factory():
    """search_attractions 的替身：每次返回全新 dict（_enrich 原地补 description/reason，
    共享常量 dict 会被上一个用例污染，导致缺响应用例意外拿到残留字段）。"""
    return [dict(p) for p in AMAP_ATTRACTIONS]


def test_researcher_amap_priority():
    """高德候选优先：description/reason 由"景点描述JSON"一次调用补写，
    weather 锚定高德候选坐标，RAG search_pois_fn 不被调用。"""
    fake = FakeProvider(json_responses={"景点描述JSON": {"items": [
        {"name": "成都塔", "description": "锦江畔电视塔，登高俯瞰全城。", "reason": "地标必打卡"},
        {"name": "锦里古街", "description": "三国主题仿古街，小吃云集。", "reason": "美食与民俗"},
    ]}})
    rag_calls = []

    def rag(name, *, query=None, k=8):
        rag_calls.append(name)
        return list(CANDIDATES)

    out = researcher.researcher_node(
        _state(), fake, weather_fn=fake_weather, search_pois_fn=rag,
        normalize_region_fn=_normalize, search_attractions_fn=lambda city: _amap_factory(),
    )  # type: ignore[arg-type]
    assert out["region_resolved"] is True
    assert [p["poi_id"] for p in out["candidates"]] == ["amap-B000A1", "amap-B000A2"]
    assert not rag_calls  # 高德命中 → RAG 不参与
    assert out["candidates"][0]["description"] == "锦江畔电视塔，登高俯瞰全城。"
    assert out["candidates"][0]["reason"] == "地标必打卡"
    assert out["candidates"][1]["description"] == "三国主题仿古街，小吃云集。"  # 名称回填
    # weather 锚定高德候选真实坐标
    assert out["weather"] and out["weather"][0]["source"] == "open-meteo"


def test_researcher_amap_empty_falls_back_to_rag():
    """高德无结果（无 key/失败/无景点）→ RAG 语义检索兜底，行为与现状一致。"""
    fake = _fake()
    out = researcher.researcher_node(_state(), fake, **_kwargs())  # type: ignore[arg-type]
    assert [p["poi_id"] for p in out["candidates"]] == ["guangzhou-001", "guangzhou-002"]
    assert out["candidates"][0]["reason"] == "夜景绝佳，适合晚上登塔"


def test_researcher_amap_llm_failure_keeps_candidates():
    """高德候选 LLM 补写失败（无"景点描述JSON"响应）→ 候选原样保留，不抛异常。"""
    out = researcher.researcher_node(
        _state(), FakeProvider(), weather_fn=fake_weather, search_pois_fn=_search,
        normalize_region_fn=_normalize, search_attractions_fn=lambda city: _amap_factory(),
    )  # type: ignore[arg-type]
    assert [p["poi_id"] for p in out["candidates"]] == ["amap-B000A1", "amap-B000A2"]
    assert out["candidates"][0].get("description") in ("", None)  # 缺省不阻塞
    assert out["candidates"][0].get("reason") in ("", None)


def test_researcher_amap_province_only_skips_amap():
    """用户只提到省份（city=None）→ 不调高德（需城市名），走 RAG 省检索。"""
    state = _state()
    state["profile"]["destination"] = "河北"
    amap_calls = []

    def normalize(name):
        return ("河北", None) if "河北" in name else _normalize(name)

    out = researcher.researcher_node(
        state, FakeProvider(), weather_fn=fake_weather, search_pois_fn=_search,
        normalize_region_fn=normalize, search_attractions_fn=lambda city: amap_calls.append(city) or _amap_factory(),
    )  # type: ignore[arg-type]
    assert amap_calls == []  # 无城市 → 高德不调用
    assert out["region_resolved"] is True and out["candidates"] == []
