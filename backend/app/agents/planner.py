"""Planner 行程规划师：画像 + 天气 + RAG 候选（景点/周边餐厅/酒店）→ 天级行程。

LLM 只产出结构化 JSON（days[] 引用 poi_id），回复文本由 format_itinerary
确定性生成 —— 遵循 spec 风险对策"结构化状态，减少自由文本流转"。
RAG 检索函数通过注入传入（默认 app.rag.retriever），测试注入假实现。
"""
from __future__ import annotations

import json
from collections.abc import Callable

from app import events
from app.llm.deepseek import DeepSeekProvider
from app.rag.retriever import get_poi as _default_get_poi
from app.rag.retriever import normalize_city as _default_normalize_city
from app.rag.retriever import search_nearby as _default_search_nearby
from app.rag.retriever import search_pois as _default_search_pois
from app.tools.weather_api import get_weather as _default_weather

PLANNER_SYSTEM_PROMPT = """你是智能旅行助手的"行程规划师"。根据用户画像、天气与候选 POI 数据，
生成逐日行程。只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{
  "days": [
    {
      "day": 1,
      "title": "当日主题，如 熊猫基地与宽窄巷子",
      "weather_note": "当日天气一句话，如 晴 24°C",
      "items": [
        {"time": "09:00", "name": "景点名", "poi_id": "候选列表中的 id，必须引用", "note": "为什么去/怎么玩，10-20 字"}
      ]
    }
  ],
  "summary": "整体行程总结，50 字以内",
  "warnings": ["提示，如 需要提前预约/雨天备选，没有则为空数组"]
}
规则：
- 每天 3-5 项，时间从早到晚；餐饮穿插在景点之间，优先选景点"周边餐厅"里的
- 必须从提供的候选 POI 中选取并引用其 poi_id，不要编造
- 雨天（condition 含 雨/雪/雷）优先安排室内景点
- 尊重用户偏好标签（美食/购物/文化/自然/亲子），缺偏好时均衡安排
- 天数以 duration_days 为准，不要多排
"""


def build_candidate_context(
    profile: dict,
    search_pois_fn: Callable,
    search_nearby_fn: Callable,
) -> str:
    """RAG 检索候选并拼成 LLM 上下文：景点（附周边餐厅）+ 酒店。"""
    city = profile["destination"]
    prefs = " ".join(profile.get("preferences", []))
    attractions = search_pois_fn(city, category="attraction", query=prefs or None, k=8)
    hotels = search_pois_fn(city, category="hotel", query=None, k=4)

    lines = ["候选景点（含周边餐厅，周边餐厅可直接选入行程）:"]
    for poi in attractions:
        nearby = search_nearby_fn(
            poi["lat"], poi["lng"], category="restaurant", radius_km=3.0, k=2
        )
        nearby_names = "、".join(r["name"] for r in nearby) or "（无）"
        lines.append(
            f"- {poi['name']}（评分{poi['rating']}，价位档{poi['price_tier']}）: {poi['description']}"
            f" | 周边餐厅: {nearby_names}"
        )
    lines.append("候选酒店:")
    for h in hotels:
        lines.append(
            f"- {h['name']}（评分{h['rating']}，价位档{h['price_tier']}）: {h['description']}"
        )
    return "\n".join(lines)


def format_itinerary(itinerary: dict) -> str:
    """把结构化行程转成中文 markdown 文本（确定性，不依赖 LLM）。"""
    lines: list[str] = []
    for day in itinerary.get("days") or []:
        lines.append(f"## 第 {day['day']} 天：{day.get('title', '')}")
        note = day.get("weather_note")
        if note:
            lines.append(f"> 天气：{note}")
        for item in day.get("items", []):
            name = item["name"]
            note_text = item.get("note")
            lines.append(f"- **{item.get('time', '')}** {name}{('（' + note_text + '）') if note_text else ''}")
        lines.append("")
    if itinerary.get("summary"):
        lines.append(f"**行程总结**：{itinerary['summary']}")
    for w in itinerary.get("warnings", []):
        lines.append(f"⚠️ {w}")
    return "\n".join(lines).strip()


def planner_node(
    state: dict,
    llm: DeepSeekProvider,
    *,
    weather_fn: Callable = _default_weather,
    search_pois_fn: Callable = _default_search_pois,
    search_nearby_fn: Callable = _default_search_nearby,
    get_poi_fn: Callable = _default_get_poi,
    normalize_city_fn: Callable = _default_normalize_city,
) -> dict:
    events.publish({"type": "agent_status", "data": {"agent": "planner", "status": "start"}})
    profile: dict = state.get("profile", {})
    destination = profile.get("destination", "")
    city = normalize_city_fn(destination) if destination else None
    if city is None:
        events.publish({"type": "agent_status", "data": {"agent": "planner", "status": "done"}})
        return {
            "phase": "answered",
            "itinerary": {},
            "last_reply": (
                f"目前暂不支持「{destination or '空'}」的行程规划，"
                "当前支持约 20 个国内旅游城市：北京、上海、成都、西安、杭州、"
                "广州、深圳、南京、苏州、重庆、厦门、青岛、大连、长沙、武汉、"
                "昆明、大理、丽江、三亚、洛阳。"
            ),
        }

    from app.rag.generate import CITY_COORDS

    lat, lng = CITY_COORDS[city]
    weather = weather_fn(lat, lng, days=profile.get("duration_days", 3))
    candidate_ctx = build_candidate_context(profile, search_pois_fn, search_nearby_fn)

    llm_messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"画像：{json.dumps(profile, ensure_ascii=False)}\n"
            f"{candidate_ctx}\n"
            f"未来 {len(weather)} 天天气：{json.dumps(weather, ensure_ascii=False)}\n"
            "请按 schema 输出行程 JSON，所有条目必须引用候选 POI 的 poi_id。"
        )},
    ]
    itinerary = llm.chat_json(llm_messages)

    # 清洗：过滤引用不存在的 poi_id 的条目（LLM 幻觉防护）
    for day in itinerary.get("days") or []:
        kept = []
        for item in day.get("items", []):
            pid = item.get("poi_id")
            if get_poi_fn(pid) is None:
                continue  # 编造的 POI 直接丢弃
            kept.append(item)
        day["items"] = kept

    source = "open-meteo" if any(w.get("source") == "open-meteo" for w in weather) else "simulated"
    reply = format_itinerary(itinerary)
    if source == "simulated":
        reply += "\n\n_（天气数据暂不可用，已用模拟数据，仅供参考）_"
    events.publish({"type": "agent_status", "data": {"agent": "planner", "status": "done"}})
    return {"phase": "answered", "itinerary": itinerary, "last_reply": reply}
