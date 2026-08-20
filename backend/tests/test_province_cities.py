"""test_province_cities.py"""
import pytest

from app.rag import province_cities as pc

# 34 省级行政区（标准口径：23 省 + 5 自治区 + 4 直辖市 + 2 特别行政区）
ALL_34 = {
    "北京", "上海", "天津", "重庆",
    "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建",
    "江西", "山东", "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州",
    "云南", "陕西", "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆",
    "香港", "澳门",
}


def test_provinces_cover_34():
    assert set(pc.PROVINCES) == ALL_34


def test_province_shape():
    for prov, d in pc.PROVINCES.items():
        assert d["alias"] and d["cities"] and d["poi_cities"]
        assert 1 <= len(d["poi_cities"]) <= 4, f"{prov}: 景点城市应为 1-4 个（直辖市/特别行政区为单城）"
        assert set(d["poi_cities"]) <= set(d["cities"]), f"{prov}: poi_cities ⊆ cities"
        for city, (pinyin, (lat, lng)) in d["poi_cities"].items():
            assert pinyin.isascii(), f"{city}: 拼音必须是 ascii"
            assert 15 <= lat <= 55 and 70 <= lng <= 140, f"{city}: 坐标越界"


def test_aliases_resolve():
    assert pc.PROVINCE_ALIASES["广东省"] == "广东"
    assert pc.PROVINCE_ALIASES["粤"] == "广东"
    assert pc.PROVINCE_ALIASES["guangdong"] == "广东"
    assert pc.PROVINCE_ALIASES["北京市"] == "北京"
    assert pc.PROVINCE_ALIASES["xinjiang"] == "新疆"


def test_city_to_province():
    assert pc.CITY_TO_PROVINCE["广州"] == "广东"
    assert pc.CITY_TO_PROVINCE["佛山"] == "广东"   # 库外城市也必须有省归属（三级检索 fallback）
    assert pc.CITY_TO_PROVINCE["成都"] == "四川"


def test_city_coord():
    lat, lng = pc.city_coord("广东", "广州")
    assert abs(lat - 23.1291) < 0.01 and abs(lng - 113.2644) < 0.01
    lat, lng = pc.city_coord("广东", None)  # 省会坐标
    assert abs(lat - 23.1291) < 0.01
    with pytest.raises(KeyError):
        pc.city_coord("巴黎", None)
