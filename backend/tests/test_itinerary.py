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
    assert item["city"] == "广州"          # 城市用于图片搜索消歧
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


def test_enrich_fills_detail_from_candidate_description():
    """detail 兜底：LLM 未写详细介绍（如注入兜底条目）时附候选 description。"""
    out = enrich_itinerary(ITINERARY, CANDIDATES)
    item = out["days"][0]["items"][0]  # 广州塔无 detail
    assert item["detail"] == "珠江畔地标。"


def test_enrich_keeps_llm_detail_over_candidate_description():
    """条目已有够长的 detail（≥40 字）时保留 LLM 原文，不被候选 description 覆盖。"""
    llm_detail = ("广州塔高600米，昵称小蛮腰，登顶可俯瞰珠江新城全景，"
                  "夜晚灯光秀不容错过，塔下有花城广场音乐喷泉。")
    it = {"days": [{"day": 1, "title": "x", "weather_note": "",
                    "items": [{"name": "广州塔", "poi_id": "guangzhou-001", "note": "",
                               "detail": llm_detail}]}],
          "summary": "", "warnings": []}
    item = enrich_itinerary(it, CANDIDATES)["days"][0]["items"][0]
    assert item["detail"] == llm_detail


def test_enrich_replaces_short_detail_with_candidate_description():
    """LLM 写的短 detail（<40 字套话）被候选 description 替换（具体介绍）。"""
    it = {"days": [{"day": 1, "title": "x", "weather_note": "",
                    "items": [{"name": "广州塔", "poi_id": "guangzhou-001", "note": "",
                               "detail": "值得一去"}]}],
          "summary": "", "warnings": []}
    item = enrich_itinerary(it, CANDIDATES)["days"][0]["items"][0]
    assert item["detail"] == "珠江畔地标。"


def test_enrich_matches_by_name_when_no_poi_id():
    """LLM 不填 poi_id 时按名称包含匹配：'白云山景区' 匹配候选 '白云山'，
    附 poi_id/坐标/description（前端图片与地图依赖这些字段）。"""
    it = {"days": [{"day": 1, "title": "x", "weather_note": "",
                    "items": [{"name": "白云山景区", "note": "登山"}]}],
          "summary": "", "warnings": []}
    item = enrich_itinerary(it, CANDIDATES)["days"][0]["items"][0]
    assert item["poi_id"] == "guangzhou-002"
    assert item["lat"] == 23.18 and item["lng"] == 113.29
    assert item["name"] == "白云山"  # 名称统一为候选名
    assert item["note"] == "登山"    # 原字段保留
    assert "detail" not in item      # 该候选故意缺 description，无兜底（数据限制）


def test_enrich_name_match_takes_longest_candidate():
    """多个候选同时包含时取名称最长者（最具体，防短名误配）。"""
    it = {"days": [{"day": 1, "title": "x", "weather_note": "",
                    "items": [{"name": "广州塔夜景观光", "note": ""}]}],
          "summary": "", "warnings": []}
    item = enrich_itinerary(it, CANDIDATES)["days"][0]["items"][0]
    assert item["poi_id"] == "guangzhou-001"  # 广州塔（4字）> 白云山（3字）


def test_enrich_name_match_rejects_short_names():
    """较短一方 <3 字不匹配（防 '白云山' 误配 '山'）。"""
    it = {"days": [{"day": 1, "title": "x", "weather_note": "",
                    "items": [{"name": "山", "note": ""}]}],
          "summary": "", "warnings": []}
    item = enrich_itinerary(it, CANDIDATES)["days"][0]["items"][0]
    assert "poi_id" not in item  # 原样保留


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


AMAP_CANDIDATES = [
    {"poi_id": "amap-B0FFH1", "name": "马旺子·川小馆(太古里店)", "city": "成都",
     "category": "restaurant", "lat": 30.6512, "lng": 104.0825,
     "address": "中纱帽街8号", "tel": "028-88888888", "photo_url": "https://a.amap.com/p1.jpg"},
    {"poi_id": "amap-B0FFH9", "name": "世外桃源酒店", "city": "成都",
     "category": "hotel", "lat": 30.66, "lng": 104.09,
     "address": None, "tel": None, "photo_url": None},
]


def test_enrich_attaches_amap_restaurant_fields():
    """引用 amap- poi_id 的餐厅条目附加真实商家字段（地址/电话/照片）。"""
    it = {"days": [{"day": 1, "title": "x", "weather_note": "",
                    "items": [{"name": "马旺子·川小馆(太古里店)", "poi_id": "amap-B0FFH1",
                               "note": "午餐", "detail": "招牌：川菜"}]}],
          "summary": "", "warnings": []}
    item = enrich_itinerary(it, AMAP_CANDIDATES)["days"][0]["items"][0]
    assert item["category"] == "restaurant"
    assert item["address"] == "中纱帽街8号"
    assert item["tel"] == "028-88888888"
    assert item["photo_url"] == "https://a.amap.com/p1.jpg"
    assert item["lat"] == 30.6512 and item["lng"] == 104.0825


def test_enrich_omits_none_amap_fields():
    """候选缺地址/电话/照片（None）时条目不附加这些字段。"""
    it = {"days": [{"day": 1, "title": "x", "weather_note": "",
                    "items": [{"name": "世外桃源酒店", "poi_id": "amap-B0FFH9",
                               "note": ""}]}],
          "summary": "", "warnings": []}
    item = enrich_itinerary(it, AMAP_CANDIDATES)["days"][0]["items"][0]
    assert item["category"] == "hotel"
    assert "address" not in item and "tel" not in item and "photo_url" not in item
    assert item["lat"] == 30.66 and item["lng"] == 104.09


def test_enrich_attaches_amap_hotel_fields():
    """accommodation 条目引用 amap- poi_id → 富化附加地址/电话/照片/坐标。"""
    cand = {"poi_id": "amap-B0FFH9", "name": "世外桃源酒店", "city": "广州",
            "category": "hotel", "lat": 23.13, "lng": 113.31,
            "address": "天河路1号", "tel": "020-12345678",
            "photo_url": "https://a.amap.com/h.jpg"}
    it = {"days": [{"day": 1, "title": "x", "weather_note": "",
                    "items": [{"name": "广州塔", "poi_id": "guangzhou-001", "note": ""}]}],
          "accommodation": [{"name": "世外桃源酒店", "poi_id": "amap-B0FFH9",
                             "days": [1, 2], "location_note": "天河区",
                             "detail": "大堂现代"}],
          "summary": "", "warnings": []}
    out = enrich_itinerary(it, [CANDIDATES[0], cand])
    acc = out["accommodation"][0]
    assert acc["category"] == "hotel"
    assert acc["address"] == "天河路1号" and acc["tel"] == "020-12345678"
    assert acc["photo_url"] == "https://a.amap.com/h.jpg"
    assert acc["lat"] == 23.13 and acc["lng"] == 113.31
    assert acc["location_note"] == "天河区" and acc["detail"] == "大堂现代"  # 原字段保留
    assert acc["days"] == [1, 2]


def test_enrich_keeps_accommodation_without_poi_id():
    """accommodation 无 poi_id（示例酒店）→ 原样保留（不做名称兜底匹配）。"""
    it = {"days": [{"day": 1, "title": "x", "weather_note": "",
                    "items": [{"name": "广州塔", "poi_id": "guangzhou-001", "note": ""}]}],
          "accommodation": [{"name": "锦江宾馆（示例）", "days": [1, 2],
                             "location_note": "锦江区"}],
          "summary": "", "warnings": []}
    out = enrich_itinerary(it, CANDIDATES)
    assert out["accommodation"] == [{"name": "锦江宾馆（示例）", "days": [1, 2],
                                     "location_note": "锦江区"}]


def test_enrich_omits_none_amap_hotel_fields():
    """候选缺地址/电话/照片（None）时 accommodation 条目不附加这些字段。"""
    it = {"days": [{"day": 1, "title": "x", "weather_note": "",
                    "items": [{"name": "广州塔", "poi_id": "guangzhou-001", "note": ""}]}],
          "accommodation": [{"name": "世外桃源酒店", "poi_id": "amap-B0FFH9",
                             "days": [1, 2], "location_note": "成都"}],
          "summary": "", "warnings": []}
    acc = enrich_itinerary(it, AMAP_CANDIDATES)["accommodation"][0]
    assert acc["category"] == "hotel"
    assert acc["lat"] == 30.66 and acc["lng"] == 104.09
    assert "address" not in acc and "tel" not in acc and "photo_url" not in acc
    assert acc["location_note"] == "成都" and acc["days"] == [1, 2]
