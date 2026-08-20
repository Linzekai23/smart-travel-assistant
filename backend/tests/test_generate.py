import pytest

from app.llm.deepseek import DeepSeekProvider
from app.rag import generate

from conftest import FakeProvider

CITY_RESPONSE = {
    "city": "成都",
    "pois": [
        {"name": "宽窄巷子", "category": "attraction", "lat": 30.67, "lng": 104.06,
         "rating": 4.6, "price_tier": 1, "description": "老成都街区，小吃与茶馆集中。",
         "tags": ["老街", "小吃"]},
        {"name": "蜀大侠火锅", "category": "restaurant", "lat": 30.66, "lng": 104.07,
         "rating": 4.5, "price_tier": 3, "description": "本地连锁火锅，麻辣鲜香。",
         "tags": ["火锅", "麻辣"]},
    ],
}


def _fake() -> FakeProvider:
    return FakeProvider(json_responses={"成都": CITY_RESPONSE})


def test_cities_cover_20():
    assert len(generate.CITIES) == 20
    assert "北京" in generate.CITIES and "成都" in generate.CITIES


def test_generate_city_parses():
    fake = _fake()
    pois = generate.generate_city(fake, "成都")  # type: ignore[arg-type]
    assert len(pois) == 2
    assert pois[0]["name"] == "宽窄巷子"
    assert pois[0]["city"] == "成都"
    assert fake.calls[0][0]["role"] == "system"


def test_validate_drops_bad_entries():
    good = {"name": "故宫", "category": "attraction", "lat": 39.9, "lng": 116.4,
            "rating": 4.8, "price_tier": 2, "description": "紫禁城。", "tags": ["历史"]}
    bad_coord = dict(good, name="坐标越界", lat=80.0, lng=200.0)
    bad_cat = dict(good, name="类别非法", category="spa")
    bad_rating = dict(good, name="评分非法", rating=9.9)
    out = generate.validate_pois("北京", [good, bad_coord, bad_cat, bad_rating])
    assert len(out) == 1 and out[0]["name"] == "故宫"


def test_validate_tags_null_tolerated():
    """tags 为 null 不崩溃：条目保留且 tags 置空，tags 为列表的条目原样保留。"""
    good = {"name": "故宫", "category": "attraction", "lat": 39.9, "lng": 116.4,
            "rating": 4.8, "price_tier": 2, "description": "紫禁城。", "tags": ["历史"]}
    bad = dict(good, name="tags空", tags=None)
    out = generate.validate_pois("北京", [good, bad])
    assert len(out) == 2
    assert out[0]["name"] == "故宫" and out[0]["tags"] == ["历史"]
    assert out[1]["name"] == "tags空" and out[1]["tags"] == []


def test_generate_city_pois_null_tolerated():
    """pois 键存在但值为 null 时不得崩溃（T4-F3）：按空列表处理。"""
    fake = FakeProvider(json_responses={"成都": {"city": "成都", "pois": None}})
    pois = generate.generate_city(fake, "成都")  # type: ignore[arg-type]
    assert pois == []


def test_validate_description_null_normalized():
    """description 为 null 时归一化为空并丢弃条目，不得残留字面 "None"（T4-F5）。"""
    good = {"name": "故宫", "category": "attraction", "lat": 39.9, "lng": 116.4,
            "rating": 4.8, "price_tier": 2, "description": "紫禁城。", "tags": ["历史"]}
    bad = dict(good, name="描述为null", description=None)
    out = generate.validate_pois("北京", [good, bad])
    assert len(out) == 1 and out[0]["name"] == "故宫"


def test_validate_tags_string_as_single_tag():
    """tags 为纯字符串时按单元素列表处理，不逐字拆分（T4-F5）。"""
    good = {"name": "故宫", "category": "attraction", "lat": 39.9, "lng": 116.4,
            "rating": 4.8, "price_tier": 2, "description": "紫禁城。", "tags": "历史"}
    out = generate.validate_pois("北京", [good])
    assert len(out) == 1
    assert out[0]["tags"] == ["历史"]
