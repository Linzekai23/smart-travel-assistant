import pytest

from app.llm.deepseek import DeepSeekProvider
from app.rag import generate
from app.rag.province_cities import PROVINCES

from conftest import FakeProvider

PROVINCE_RESPONSE = {
    "province": "四川",
    "pois": [
        {"name": "宽窄巷子", "city": "成都", "lat": 30.67, "lng": 104.06,
         "rating": 4.6, "price_tier": 1, "description": "老成都街区，小吃与茶馆集中。",
         "tags": ["老街", "小吃"]},
        {"name": "峨眉山", "city": "乐山", "lat": 29.55, "lng": 103.77,
         "rating": 4.8, "price_tier": 2, "description": "佛教名山，金顶云海。",
         "tags": ["自然", "佛教"]},
        {"name": "非法城市景点", "city": "攀枝花", "lat": 26.58, "lng": 101.71,
         "rating": 4.0, "price_tier": 1, "description": "该城市不在本省 poi_cities。",
         "tags": []},
        {"name": "非法类别", "city": "成都", "category": "restaurant", "lat": 30.6,
         "lng": 104.0, "rating": 4.0, "price_tier": 3, "description": "餐厅不应出现在语料。",
         "tags": ["火锅"]},
    ],
}


def _fake() -> FakeProvider:
    return FakeProvider(json_responses={"四川": PROVINCE_RESPONSE})


def test_province_order_covers_34():
    assert len(generate.PROVINCE_ORDER) == 34
    assert generate.PROVINCE_ORDER[0] == "北京"
    assert set(generate.PROVINCE_ORDER) == set(PROVINCES)


def test_city_en_derived_from_provinces():
    assert generate.CITY_EN["广州"] == "guangzhou"
    assert generate.CITY_EN["成都"] == "chengdu"
    assert set(generate.CITY_EN) == {
        c for d in PROVINCES.values() for c in d["poi_cities"]
    }


def test_generate_province_parses():
    fake = _fake()
    pois = generate.generate_province(fake, "四川")  # type: ignore[arg-type]
    assert len(pois) == 2  # 非法城市与非法类别被丢弃
    assert pois[0]["name"] == "宽窄巷子"
    assert pois[0]["province"] == "四川" and pois[0]["city"] == "成都"
    assert fake.calls[0][0]["role"] == "system"
    assert "示例数据" in fake.calls[0][0]["content"]  # 语料标注


def test_validate_pois_checks_city_and_coord():
    good = {"name": "故宫", "city": "北京", "lat": 39.9, "lng": 116.4,
            "rating": 4.8, "price_tier": 2, "description": "紫禁城。", "tags": ["历史"]}
    bad_city = dict(good, name="外地景点", city="成都")
    bad_coord = dict(good, name="坐标越界", lat=80.0, lng=200.0)
    out = generate.validate_pois("北京", [good, bad_city, bad_coord])
    assert len(out) == 1 and out[0]["name"] == "故宫"


def test_validate_tags_null_tolerated():
    good = {"name": "故宫", "city": "北京", "lat": 39.9, "lng": 116.4,
            "rating": 4.8, "price_tier": 2, "description": "紫禁城。", "tags": ["历史"]}
    bad = dict(good, name="tags空", tags=None)
    out = generate.validate_pois("北京", [good, bad])
    assert len(out) == 2
    assert out[1]["tags"] == []


def test_generate_pois_null_tolerated():
    """pois: null 不得崩溃，按空列表处理（T4-F3 回归保持）。"""
    fake = FakeProvider(json_responses={"四川": {"province": "四川", "pois": None}})
    assert generate.generate_province(fake, "四川") == []  # type: ignore[arg-type]


def test_validate_tags_string_as_single_tag():
    """tags 为纯字符串时按单元素列表处理，不逐字拆分（T4-F5）。"""
    good = {"name": "故宫", "city": "北京", "lat": 39.9, "lng": 116.4,
            "rating": 4.8, "price_tier": 2, "description": "紫禁城。", "tags": "历史"}
    out = generate.validate_pois("北京", [good])
    assert len(out) == 1
    assert out[0]["tags"] == ["历史"]


def test_validate_description_null_normalized():
    """description 为 null 时归一化为空并丢弃条目，不得残留字面 "None"（T4-F5）。"""
    good = {"name": "故宫", "city": "北京", "lat": 39.9, "lng": 116.4,
            "rating": 4.8, "price_tier": 2, "description": "紫禁城。", "tags": ["历史"]}
    bad = dict(good, name="描述为null", description=None)
    out = generate.validate_pois("北京", [good, bad])
    assert len(out) == 1 and out[0]["name"] == "故宫"


def test_generate_province_existing_hints_prompt():
    """增量扩量：已有 (city, name) 清单进 prompt，提示 LLM 避开（降低轮次间重复）。"""
    fake = FakeProvider(json_responses={"四川": PROVINCE_RESPONSE})
    generate.generate_province(fake, "四川",  # type: ignore[arg-type]
                               existing={("成都", "宽窄巷子"), ("成都", "武侯祠"), ("北京", "故宫")})
    user = fake.calls[0][-1]["content"]
    assert "已有景点" in user and "成都·宽窄巷子" in user and "成都·武侯祠" in user
    assert "北京·故宫" not in user  # 其他省的已有条目不进本省提示


def test_merge_unique_filters_same_city_name():
    """多轮累积去重：同城同名过滤；不同城市同名（如多地中山公园）允许共存；existing 同步更新。"""
    a = {"city": "北京", "name": "故宫"}
    b = {"city": "北京", "name": "天坛"}
    c = {"city": "上海", "name": "中山公园"}
    d = {"city": "北京", "name": "中山公园"}  # 同省不同市同名 → 不判重
    existing = {("北京", "故宫")}
    added = generate.merge_unique([a, b, c, d], existing)
    assert [p["name"] for p in added] == ["天坛", "中山公园", "中山公园"]
    assert ("北京", "天坛") in existing and ("上海", "中山公园") in existing
    # 再次 merge 同一批 → 全部已存在，无新增
    assert generate.merge_unique([a, b, c, d], existing) == []
