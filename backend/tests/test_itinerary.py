"""enrich_itinerary：行程条目按 poi_id 附加候选坐标（地图数据链路的起点）。"""
from app.itinerary import enrich_itinerary

CANDIDATES = [
    {"poi_id": "guangzhou-001", "city": "广州", "name": "广州塔",
     "category": "attraction", "lat": 23.1066, "lng": 113.3245,
     "rating": 4.6, "price_tier": 3, "description": "珠江畔地标。", "reason": "夜景绝佳"},
    {"poi_id": "guangzhou-002", "city": "广州", "name": "白云山",
     "category": "attraction", "lat": 23.18, "lng": 113.29},  # 故意缺 description/reason
]

ITINERARY = {
    "days": [{"day": 1, "title": "广州地标", "weather_note": "晴",
              "items": [{"name": "广州塔", "poi_id": "guangzhou-001",
                         "suggested_time": "建议晚上 19:00 后前往", "time_reason": "夜景绝佳",
                         "note": "夜景"},
                        {"name": "点都德（示例）", "note": "午餐"},
                        {"name": "未命中景点", "poi_id": "nope-999", "note": ""}]}],
    "summary": "OK", "warnings": [],
}


def test_enrich_attaches_candidate_coords():
    out = enrich_itinerary(ITINERARY, CANDIDATES)
    item = out["days"][0]["items"][0]
    assert item["poi_id"] == "guangzhou-001"
    assert item["lat"] == 23.1066
    assert item["lng"] == 113.3245
    assert item["name"] == "广州塔"        # 富化后 name 取自候选
    assert item["category"] == "attraction"
    assert item["reason"] == "夜景绝佳"
    assert item["description"] == "珠江畔地标。"
    assert item["note"] == "夜景"          # 原字段保留


def test_enrich_keeps_items_without_poi_id():
    out = enrich_itinerary(ITINERARY, CANDIDATES)
    food = out["days"][0]["items"][1]
    assert food == {"name": "点都德（示例）", "note": "午餐"}  # 无 poi_id 原样


def test_enrich_keeps_unmatched_poi_id():
    out = enrich_itinerary(ITINERARY, CANDIDATES)
    miss = out["days"][0]["items"][2]
    assert "lat" not in miss and miss["poi_id"] == "nope-999"  # 未命中不附加


def test_enrich_tolerates_missing_candidate_fields():
    out = enrich_itinerary(ITINERARY, CANDIDATES)
    # guangzhou-002 缺 description/reason：构造一个引用它的行程验证字段缺失时不附加
    it = {"days": [{"day": 1, "title": "x", "weather_note": "",
                    "items": [{"name": "白云山", "poi_id": "guangzhou-002", "note": ""}]}],
          "summary": "", "warnings": []}
    item = enrich_itinerary(it, CANDIDATES)["days"][0]["items"][0]
    assert item["lat"] == 23.18 and item["lng"] == 113.29
    assert "reason" not in item and "description" not in item


def test_enrich_empty_candidates():
    out = enrich_itinerary(ITINERARY, [])
    assert out["days"][0]["items"][0] == ITINERARY["days"][0]["items"][0]
    assert "lat" not in out["days"][0]["items"][0]


def test_enrich_does_not_mutate_input():
    before = {"name": "广州塔", "poi_id": "guangzhou-001",
              "suggested_time": "建议晚上 19:00 后前往", "time_reason": "夜景绝佳", "note": "夜景"}
    itinerary = {"days": [{"day": 1, "title": "t", "weather_note": "",
                           "items": [dict(before)]}], "summary": "", "warnings": []}
    enrich_itinerary(itinerary, CANDIDATES)
    assert itinerary["days"][0]["items"][0] == before  # 入参未被原地修改


def test_enrich_days_none_passthrough():
    out = enrich_itinerary({"days": None, "summary": "x", "warnings": []}, CANDIDATES)
    assert out["days"] is None  # days: None 透传（planner days-None 降级分支依赖此语义）
