"""Researcher 研究员：RAG 三级粒度检索景点候选 + 实时天气 + LLM 推荐要点。

LLM 只产出结构化 JSON（recommendations 引用 poi_id）；candidates 元素为
POI dict + reason（推荐理由），供 Planner 消费。
"""
from __future__ import annotations

import json
from collections.abc import Callable

from app import events
from app.llm.deepseek import DeepSeekProvider
from app.rag.province_cities import city_coord
from app.rag.retriever import normalize_region as _default_normalize_region
from app.rag.retriever import search_pois as _default_search_pois
from app.tools.weather_api import get_weather as _default_weather

RESEARCHER_SYSTEM_PROMPT = """你是智能旅行助手的"研究员"。根据候选景点列表，为每条候选生成一句话推荐理由（10-20 字，如 亲子友好/夜景绝佳/世界遗产）。
只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{"recommendations": [
  {"poi_id": "候选列表中的 id，必须引用", "reason": "一句话推荐理由"}
]}
- 最多选 5 条最贴合用户偏好的候选；偏好不明确时选评分最高的"""


def researcher_node(
    state: dict,
    llm: DeepSeekProvider,
    *,
    weather_fn: Callable = _default_weather,
    search_pois_fn: Callable = _default_search_pois,
    normalize_region_fn: Callable = _default_normalize_region,
) -> dict:
    events.publish({"type": "agent_status", "data": {"agent": "researcher", "status": "start"}})
    profile: dict = state.get("profile", {})
    destination = str(profile.get("destination", "") or "")
    province, city = normalize_region_fn(destination)
    if province is None:
        events.publish({"type": "agent_status", "data": {"agent": "researcher", "status": "done"}})
        return {"candidates": [], "weather": [], "region_resolved": False}

    prefs = " ".join(profile.get("preferences", []))
    candidates = search_pois_fn(destination, query=prefs or None, k=8)

    if candidates:
        messages = [
            {"role": "system", "content": RESEARCHER_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"用户偏好：{prefs or '未明确'}。\n候选景点："
                f"{json.dumps([{'poi_id': p['poi_id'], 'name': p['name'], 'city': p['city'], 'rating': p['rating'], 'description': p['description']} for p in candidates], ensure_ascii=False)}\n"
                "请按 schema 输出推荐要点 JSON（标记词：推荐要点JSON）。"
            )},
        ]
        try:
            recs = llm.chat_json(messages)
        except (AssertionError, ValueError, KeyError, TypeError):
            recs = {}
        reasons = {r.get("poi_id"): str(r.get("reason", "")) for r in (recs.get("recommendations") or []) if isinstance(r, dict)}
        for p in candidates:
            p["reason"] = reasons.get(p["poi_id"], "")

    lat, lng = (float(candidates[0]["lat"]), float(candidates[0]["lng"])) if candidates else city_coord(province, None)
    weather = weather_fn(lat, lng, days=profile.get("duration_days", 3))
    events.publish({"type": "agent_status", "data": {"agent": "researcher", "status": "done"}})
    return {"candidates": candidates, "weather": weather, "region_resolved": True}
