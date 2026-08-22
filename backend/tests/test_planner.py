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
              "items": [{"name": "广州塔", "poi_id": "guangzhou-001",
                         "suggested_time": "建议晚上 19:00 后前往", "time_reason": "夜景绝佳、江风凉爽",
                         "note": "夜景",
                         "detail": "广州塔高600米，昵称小蛮腰，登顶可俯瞰珠江新城全景，夜晚灯光秀不容错过。"},
                        {"name": "点都德（示例）", "note": "午餐",
                         "detail": "招牌：虾饺、红米肠、艇仔粥"}]}],
    "accommodation": [{"name": "锦江宾馆（示例）", "days": [1, 2],
                       "location_note": "锦江区，近春熙路",
                       "commute_note": "到当日景点约 15-30 分钟车程",
                       "price_note": "中档，符合预算",
                       "detail": "大堂现代、带健身房与自助早餐，近地铁口"}],
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
                  "items": [{"name": "编造的景点", "poi_id": "nope-999", "note": ""}]}],
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
                  "items": [{"name": "点都德（示例）", "note": "午餐"}]}],
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


def test_format_itinerary_includes_accommodation():
    text = planner.format_itinerary(ITINERARY)
    assert "🏨" in text
    assert "锦江宾馆（示例）" in text and "第1天" in text and "第2天" in text
    assert "锦江区，近春熙路" in text          # 位置理由
    assert "到当日景点约 15-30 分钟车程" in text  # 通勤理由
    assert "中档，符合预算" in text             # 价格理由
    assert "大堂现代、带健身房与自助早餐" in text  # 住宿环境


def test_format_itinerary_includes_detail():
    text = planner.format_itinerary(ITINERARY)
    assert "小蛮腰" in text and "> " in text     # 景点详细介绍
    assert "招牌：虾饺、红米肠" in text           # 餐厅推荐美食


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
                                   "items": [{"name": "点都德（示例）", "note": "午餐"}]}],
                         "summary": "x", "warnings": []},
        "上一版行程没有引用": {"days": [{"day": 1, "title": "x", "weather_note": "晴",
                                         "items": [{"name": "广州塔", "poi_id": "guangzhou-001",
                                                    "suggested_time": "建议上午 8:00-10:00 前往",
                                                    "time_reason": "清晨人少", "note": ""}]}],
                               "summary": "x", "warnings": []},
    })
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert len(fake.calls) == 2  # 重试了一次（第二次行程只有 poi_id 条目，无需补全）
    assert "上一版行程没有引用" in fake.calls[1][-1]["content"]  # 纠正指令送达
    item = out["itinerary"]["days"][0]["items"][0]
    assert item["poi_id"] == "guangzhou-001"
    assert item["lat"] == 23.1066  # 富化正常（现有集成）


def test_planner_zero_reference_twice_still_terminates():
    """两轮都零引用 → 不再重试，注入 top 候选兜底，正常格式化（不无限循环）。"""
    zero_ref = {"days": [{"day": 1, "title": "x", "weather_note": "晴",
                          "items": [{"name": "点都德（示例）", "note": "午餐"}]}],
                "summary": "x", "warnings": []}
    fake = FakeProvider(json_responses={"行程规划JSON": zero_ref,
                                        "上一版行程没有引用": zero_ref,
                                        "景点补全": {"items": []}})
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert len(fake.calls) == 3  # 行程 + 纠正重试 + 补全
    assert out["last_reply"].startswith("## ")


def test_planner_llm_exception_no_retry():
    """LLM 异常 → 不重试，走 days-None 降级。"""
    fake = FakeProvider()  # 无响应配置 → chat_json 抛 AssertionError
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert len(fake.calls) == 1
    assert out["last_reply"] == "行程总结："


def test_planner_injects_distinct_candidate_per_day():
    """零引用兜底逐天注入：每天一个不同候选（3 天 → 广州塔/白云山，不重复）。"""
    zero_ref = {"days": [{"day": 1, "title": "x", "weather_note": "晴",
                          "items": [{"name": "点都德（示例）", "note": "午餐"}]},
                         {"day": 2, "title": "x", "weather_note": "晴",
                          "items": [{"name": "陶陶居（示例）", "note": "午餐"}]},
                         {"day": 3, "title": "x", "weather_note": "晴",
                          "items": [{"name": "莲香楼（示例）", "note": "午餐"}]}],
                "summary": "x", "warnings": []}
    fake = FakeProvider(json_responses={"行程规划JSON": zero_ref,
                                        "上一版行程没有引用": zero_ref,
                                        "景点补全": {"items": []}})
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    days = out["itinerary"]["days"]
    assert days[0]["items"][0]["poi_id"] == "guangzhou-001"  # 逐天取不同候选
    assert days[1]["items"][0]["poi_id"] == "guangzhou-002"
    assert "poi_id" not in days[2]["items"][0]  # 候选耗尽后不再注入（不重复景点）
    assert days[0]["items"][0]["suggested_time"] == "上午 8:00-10:00 前往"
    assert days[1]["items"][0]["suggested_time"] == "下午 14:00-16:00 前往"
    assert days[0]["items"][0]["detail"] == "珠江畔地标。"  # enrich 用候选 description 兜底 detail


def test_planner_supplements_extra_attractions(monkeypatch, tmp_path):
    """语料外景点（无 poi_id 且名称未匹配候选）→ 补全调用生成具体介绍 + 景点标记。"""
    monkeypatch.setattr(planner, "_detail_cache_path", lambda: tmp_path / "details.json")
    itin = {"days": [{"day": 1, "title": "x", "weather_note": "晴",
                      "items": [{"name": "广州塔", "poi_id": "guangzhou-001", "note": ""},
                                {"name": "锦里古街", "note": "逛古街"}]}],
            "summary": "x", "warnings": []}
    detail = ("锦里是成都武侯祠旁的仿古商业街，免费开放，主打川西民俗与小吃，"
              "建议游玩2-3小时，地铁3号线高升桥站可达，晚上灯笼亮起更有味道。")
    fake = FakeProvider(json_responses={
        "行程规划JSON": itin,
        "景点补全": {"items": [{"name": "锦里古街", "is_attraction": True,
                               "detail": detail}]}})
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    item = out["itinerary"]["days"][0]["items"][1]
    assert item["category"] == "attraction"  # 前端据此渲染图片
    assert item["detail"] == detail
    assert len(fake.calls) == 2  # 行程 + 补全


def test_planner_supplement_keeps_non_attraction_unchanged(monkeypatch, tmp_path):
    """补全判定为餐厅 → 不加景点标记、不覆盖 detail。"""
    monkeypatch.setattr(planner, "_detail_cache_path", lambda: tmp_path / "details.json")
    itin = {"days": [{"day": 1, "title": "x", "weather_note": "晴",
                      "items": [{"name": "广州塔", "poi_id": "guangzhou-001", "note": ""},
                                {"name": "蜀风园（示例）", "note": "午餐",
                                 "detail": "招牌：龙抄手"}]}],
            "summary": "x", "warnings": []}
    fake = FakeProvider(json_responses={
        "行程规划JSON": itin,
        "景点补全": {"items": [{"name": "蜀风园（示例）", "is_attraction": False,
                               "detail": ""}]}})
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    item = out["itinerary"]["days"][0]["items"][1]
    assert "category" not in item
    assert item["detail"] == "招牌：龙抄手"  # 原样保留


def test_planner_supplement_caches_and_skips_second_call(monkeypatch, tmp_path):
    """同一景点补全结果按名称缓存：第二次行程不再调用补全 LLM。"""
    cache_file = tmp_path / "details.json"
    monkeypatch.setattr(planner, "_detail_cache_path", lambda: cache_file)
    itin = {"days": [{"day": 1, "title": "x", "weather_note": "晴",
                      "items": [{"name": "广州塔", "poi_id": "guangzhou-001", "note": ""},
                                {"name": "锦里古街", "note": ""}]}],
            "summary": "x", "warnings": []}
    detail = "锦里是成都武侯祠旁的仿古商业街，免费开放，建议游玩2-3小时。"
    fake = FakeProvider(json_responses={
        "行程规划JSON": itin,
        "景点补全": {"items": [{"name": "锦里古街", "is_attraction": True,
                               "detail": detail}]}})
    planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert len(fake.calls) == 2  # 第一次：行程 + 补全
    assert cache_file.exists()
    fake2 = FakeProvider(json_responses={"行程规划JSON": itin})
    out = planner.planner_node(_state(), fake2)  # type: ignore[arg-type]
    assert len(fake2.calls) == 1  # 第二次：缓存命中，无补全调用
    assert out["itinerary"]["days"][0]["items"][1]["detail"] == detail


def test_planner_supplement_tolerates_llm_failure(monkeypatch, tmp_path):
    """补全 LLM 异常 → 条目保持原样，行程正常返回（不阻塞）。"""
    monkeypatch.setattr(planner, "_detail_cache_path", lambda: tmp_path / "details.json")
    itin = {"days": [{"day": 1, "title": "x", "weather_note": "晴",
                      "items": [{"name": "广州塔", "poi_id": "guangzhou-001", "note": ""},
                                {"name": "锦里古街", "note": "逛古街", "detail": "老街"}]}],
            "summary": "x", "warnings": []}
    fake = FakeProvider(json_responses={"行程规划JSON": itin})  # 无补全响应 → 抛异常被吞
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    item = out["itinerary"]["days"][0]["items"][1]
    assert "category" not in item
    assert item["detail"] == "老街"  # 原样


def test_planner_prompt_requires_candidate_reference():
    assert "每天必须至少安排 1-2 个候选景点并引用其 poi_id" in planner.PLANNER_SYSTEM_PROMPT


def test_planner_injects_top_candidate_after_two_zero_reference_rounds():
    """两轮 LLM 零引用 → 确定性注入 top-1 候选（带坐标，地图必有点）。"""
    zero_ref = {"days": [{"day": 1, "title": "x", "weather_note": "晴",
                          "items": [{"name": "点都德（示例）", "note": "午餐"}]}],
                "summary": "x", "warnings": []}
    fake = FakeProvider(json_responses={"行程规划JSON": zero_ref,
                                        "上一版行程没有引用": zero_ref,
                                        "景点补全": {"items": []}})
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert len(fake.calls) == 3  # 行程 + 纠正重试 + 补全（补全响应空 = 无景点）
    item = out["itinerary"]["days"][0]["items"][0]
    assert item["poi_id"] == "guangzhou-001"  # CANDIDATES[0]（广州塔）
    assert item["name"] == "广州塔"
    assert item["note"] == "推荐安排"
    assert item["suggested_time"] == "上午 8:00-10:00 前往"  # 注入兜底带建议时段
    assert item["lat"] == 23.1066  # 富化正常
