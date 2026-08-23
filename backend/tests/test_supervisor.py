from app.agents import supervisor

from conftest import FakeProvider

ITINERARY = {
    "days": [{"day": 1, "title": "广州地标", "weather_note": "晴 24°C",
              "items": [{"name": "广州塔", "poi_id": "guangzhou-001",
                         "suggested_time": "建议晚上 19:00 后前往", "time_reason": "夜景绝佳",
                         "note": "夜景",
                         "detail": "广州塔高600米，昵称小蛮腰，可俯瞰珠江新城。"}]}],
    "accommodation": [{"name": "锦江宾馆（示例）", "days": [1, 2],
                       "location_note": "锦江区，近春熙路",
                       "commute_note": "到当日景点约 15-30 分钟车程",
                       "price_note": "中档，符合预算",
                       "detail": "大堂现代、带自助早餐"}],
    "summary": "首日珠江夜景线。", "warnings": [],
}
BUDGET = {
    "items": [{"category": "住宿", "amount": 3200, "note": "中档酒店"}],
    "total": 3200, "checked": True, "scaled": False,
}
WEATHER = [{"date": "2026-10-01", "t_max": 24.0, "t_min": 16.0,
            "condition": "晴", "source": "open-meteo"}]


def _state():
    return {
        "messages": [], "phase": "planning",
        "profile": {"destination": "广州", "duration_days": 3, "budget_cny": 8000},
        "itinerary": ITINERARY, "budget_plan": BUDGET, "weather": WEATHER,
    }


def test_supervisor_reply_contains_all_sections():
    fake = FakeProvider(json_responses={"汇总JSON": {
        "summary": "整体节奏合理，预算充裕。", "tips": ["周三起降温，带外套", "广州塔建议提前预约"],
    }})
    out = supervisor.supervisor_node(_state(), fake)  # type: ignore[arg-type]
    assert out["phase"] == "answered"
    assert out["supervisor_summary"]["summary"] == "整体节奏合理，预算充裕。"
    reply = out["last_reply"]
    assert "第 1 天" in reply          # 行程 markdown
    assert "## 预算分配" not in reply  # 预算表只在右侧面板
    assert "右侧面板" in reply         # 面板指引
    assert "**总体建议**" in reply     # summary
    assert "💡" in reply               # tips
    assert "模拟数据" not in reply     # open-meteo 无脚注


def test_supervisor_llm_failure_fallback():
    """LLM 未配置响应（抛异常）→ 纯确定性拼装，行程仍在（预算表在右侧面板）。"""
    out = supervisor.supervisor_node(_state(), FakeProvider())  # type: ignore[arg-type]
    assert out["supervisor_summary"] == {"summary": "", "tips": []}
    assert "第 1 天" in out["last_reply"]
    assert "## 预算分配" not in out["last_reply"]


def test_supervisor_simulated_weather_footnote():
    weather = [{"date": "2026-10-01", "t_max": 24.0, "t_min": 16.0,
                "condition": "晴", "source": "simulated"}]
    state = _state()
    state["weather"] = weather
    out = supervisor.supervisor_node(state, FakeProvider())  # type: ignore[arg-type]
    assert "模拟数据" in out["last_reply"]


def test_supervisor_drops_non_string_tips():
    """tips 混入 None/数字 → 丢弃非字符串项，不渲染「💡 None」。"""
    fake = FakeProvider(json_responses={"汇总JSON": {
        "summary": "整体节奏合理。", "tips": ["带伞", None, 123],
    }})
    out = supervisor.supervisor_node(_state(), fake)  # type: ignore[arg-type]
    assert out["supervisor_summary"]["tips"] == ["带伞"]
    reply = out["last_reply"]
    assert "💡 带伞" in reply
    assert "💡 None" not in reply
    assert "💡 123" not in reply


def test_format_supervisor_reply_skips_empty_budget():
    text = supervisor.format_supervisor_reply(ITINERARY, {"items": [], "total": None}, WEATHER, "不错", ["带伞"])
    assert "## 预算分配" not in text
    assert "**总体建议**：不错" in text


def test_supervisor_filters_tips_duplicating_warnings():
    """tips 与行程 warnings 高度重叠 → 丢弃，避免总结卡重复提醒（雷暴/预约回归）。"""
    state = _state()
    state["itinerary"]["warnings"] = ["第三天有雷暴，建议携带雨具", "熊猫基地需提前预约门票"]
    fake = FakeProvider(json_responses={"汇总JSON": {
        "summary": "OK。",
        "tips": ["第三天有雷暴，备好雨具并减少户外活动", "熊猫基地需提前预约门票",
                 "预算充足，可适当升级美食体验"],
    }})
    out = supervisor.supervisor_node(state, fake)  # type: ignore[arg-type]
    assert out["supervisor_summary"]["tips"] == ["预算充足，可适当升级美食体验"]
