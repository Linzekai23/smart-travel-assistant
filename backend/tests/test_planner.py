import json

from app.agents import planner

from conftest import FakeProvider, fake_weather

ITINERARY = {
    "days": [
        {
            "day": 1,
            "title": "熊猫基地与宽窄巷子",
            "weather_note": "晴 24°C",
            "items": [
                {"time": "09:00", "name": "宽窄巷子", "poi_id": "chengdu-001", "note": "早到避开人流"},
                {"time": "12:00", "name": "蜀大侠火锅（春熙路店）", "poi_id": "chengdu-002", "note": "午餐"},
            ],
        }
    ],
    "summary": "首日老成都街区线。",
    "warnings": [],
}


def _fake() -> FakeProvider:
    return FakeProvider(json_responses={"行程": ITINERARY})


def _state() -> dict:
    return {
        "messages": [{"role": "user", "content": "10月去成都玩3天，预算8000，喜欢美食"}],
        "phase": "planning",
        "profile": {
            "destination": "成都", "duration_days": 1, "start_date": "2026-10-01",
            "budget_cny": 8000, "travelers": 2, "preferences": ["美食"],
        },
    }


# 注入的假检索器：行为与 retriever 契约一致，但数据可控
def _fake_search_pois(city, *, category=None, query=None, k=10):
    assert category is not None  # Planner 必须显式传类别
    pool = {
        "attraction": [{"poi_id": "chengdu-001", "city": "成都", "name": "宽窄巷子",
                        "category": "attraction", "rating": 4.6, "price_tier": 1,
                        "lat": 30.67, "lng": 104.06, "description": "老成都街区。", "tags": ["老街"]}],
        "restaurant": [{"poi_id": "chengdu-002", "city": "成都", "name": "蜀大侠火锅（春熙路店）",
                        "category": "restaurant", "rating": 4.5, "price_tier": 3,
                        "lat": 30.66, "lng": 104.07, "description": "麻辣火锅。", "tags": ["火锅"]}],
        "hotel": [{"poi_id": "chengdu-003", "city": "成都", "name": "成都群光君悦酒店",
                   "category": "hotel", "rating": 4.7, "price_tier": 4,
                   "lat": 30.66, "lng": 104.08, "description": "春熙路商圈豪华酒店。", "tags": ["商圈"]}],
    }
    return pool[category]


def _fake_search_nearby(lat, lng, *, category=None, radius_km=3.0, k=5):
    if category == "restaurant":
        return [{"poi_id": "chengdu-002", "city": "成都", "name": "蜀大侠火锅（春熙路店）",
                 "category": "restaurant", "rating": 4.5, "price_tier": 3,
                 "lat": 30.66, "lng": 104.07, "description": "麻辣火锅。", "tags": ["火锅"]}]
    return []


def _fake_get_poi(poi_id):
    return _fake_search_pois("成都", category="attraction")[0] if poi_id == "chengdu-001" else None


def _fake_normalize_city(name):
    return "成都" if "成都" in name else None


def _kwargs():
    return {
        "weather_fn": fake_weather,
        "search_pois_fn": _fake_search_pois,
        "search_nearby_fn": _fake_search_nearby,
        "get_poi_fn": _fake_get_poi,
        "normalize_city_fn": _fake_normalize_city,
    }


def test_planner_produces_reply_and_itinerary():
    fake = _fake()
    out = planner.planner_node(_state(), fake, **_kwargs())  # type: ignore[arg-type]
    assert out["phase"] == "answered"
    assert out["itinerary"]["days"][0]["items"][0]["poi_id"] == "chengdu-001"
    assert out["last_reply"].startswith("## ")


def test_planner_prompt_contains_candidates_and_weather():
    fake = _fake()
    planner.planner_node(_state(), fake, **_kwargs())  # type: ignore[arg-type]
    prompt = fake.calls[0][-1]["content"]
    assert "宽窄巷子" in prompt          # 景点候选进上下文
    assert "蜀大侠火锅" in prompt        # 周边餐厅进上下文
    assert "成都群光君悦酒店" in prompt  # 酒店候选进上下文
    assert "poi_id" in prompt            # 要求引用 POI id
    assert "晴" in prompt                # 天气进上下文


def test_planner_unknown_city_returns_hint():
    fake = _fake()
    state = _state()
    state["profile"]["destination"] = "巴黎"

    def normalize(name):
        return None

    kwargs = _kwargs()
    kwargs["normalize_city_fn"] = normalize
    out = planner.planner_node(state, fake, **kwargs)  # type: ignore[arg-type]
    assert out["phase"] == "answered"
    assert "巴黎" in out["last_reply"]
    assert "暂不支持" in out["last_reply"]
    assert fake.calls == []  # 未知城市不调用 LLM


def test_planner_filters_hallucinated_poi():
    fake = FakeProvider(json_responses={"行程": {
        "days": [{"day": 1, "title": "x", "weather_note": "晴",
                  "items": [{"time": "09:00", "name": "编造的店", "poi_id": "nope-999", "note": ""}]}],
        "summary": "x", "warnings": [],
    }})
    out = planner.planner_node(_state(), fake, **_kwargs())  # type: ignore[arg-type]
    assert out["itinerary"]["days"][0]["items"] == []  # 不存在的 poi_id 被清洗


def test_format_itinerary_shape():
    text = planner.format_itinerary(ITINERARY)
    assert "第 1 天" in text and "宽窄巷子" in text
    assert "09:00" in text and "早到避开人流" in text
    assert "## " in text
