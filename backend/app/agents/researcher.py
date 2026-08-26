"""Researcher 研究员：景点候选（高德真实 POI 优先、RAG 语义检索兜底）+ 实时天气 + LLM 推荐要点。

候选获取：用户提到城市（如"佛山"）→ 先高德搜该城真实景点；无 key/失败/无结果 →
回落到 RAG 三级粒度检索（含库外城市省兜底）。高德候选缺 description/rating，
由一次 LLM 调用批量补写介绍与推荐理由。candidates 元素为 POI dict + reason，供 Planner 消费。
"""
from __future__ import annotations

import json
from collections.abc import Callable

from app import events
from app.api import amap_poi as amap_poi_mod
from app.llm.deepseek import DeepSeekProvider
from app.rag.province_cities import city_coord
from app.rag.retriever import normalize_region as _default_normalize_region
from app.rag.retriever import search_pois as _default_search_pois
from app.tools.weather_api import get_weather as _default_weather

# 高德真实景点检索（模块级注入点：测试 monkeypatch 替换为 fake，防真实 HTTP）
_amap_service = amap_poi_mod.service

RESEARCHER_SYSTEM_PROMPT = """你是智能旅行助手的"研究员"。根据候选景点列表，为每条候选生成一句话推荐理由（10-20 字，如 亲子友好/夜景绝佳/世界遗产）。
只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{"recommendations": [
  {"poi_id": "候选列表中的 id，必须引用", "reason": "一句话推荐理由"}
]}
- 最多选 5 条最贴合用户偏好的候选；偏好不明确时选评分最高的"""

AMAP_DESCRIPTION_PROMPT = """你是智能旅行助手的"研究员"。以下是高德检索到的真实候选景点，请为每条生成介绍与推荐理由。
只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{"items": [
  {"name": "候选名，必须与列表完全一致", "description": "150-250 字：历史沿革/文化背景 + 主要看点（具体点位/分区/建筑/景观，信息密度高，避免套话）+ 游玩建议（推荐路线、建议时长、最佳时段）+ 交通提示", "reason": "10-20 字：推荐理由，贴合用户偏好"}
]}
- 覆盖所有候选；description 只写常识性内容，不要编造无法确认的门票价格与开放时间"""


def _enrich_amap_candidates(candidates: list[dict], llm: DeepSeekProvider, prefs: str) -> None:
    """高德候选（有坐标/地址/照片，无 description/rating）→ 一次 LLM 调用批量补写。

    按 name 精确匹配优先、双向包含兜底（LLM 可能微调名称）；失败/漏条 →
    候选原样保留（description/reason 缺省），不阻塞链路。"""
    messages = [
        {"role": "system", "content": AMAP_DESCRIPTION_PROMPT},
        {"role": "user", "content": (
            f"用户偏好：{prefs or '未明确'}。\n候选景点："
            f"{json.dumps([{'name': p['name'], 'city': p['city']} for p in candidates], ensure_ascii=False)}\n"
            "请按 schema 输出景点描述 JSON（标记词：景点描述JSON）。"
        )},
    ]
    try:
        items = llm.chat_json(messages).get("items") or []
    except (AssertionError, ValueError, KeyError, TypeError, RuntimeError):
        return
    infos = {str(i.get("name") or ""): i for i in items if isinstance(i, dict)}
    for p in candidates:
        name = p["name"]
        info = infos.get(name) or next(
            (v for k, v in infos.items() if (k and name) and (k in name or name in k)), None)
        if info:
            p["description"] = str(info.get("description") or "").strip() or p.get("description", "")
            p["reason"] = str(info.get("reason") or "").strip()


def researcher_node(
    state: dict,
    llm: DeepSeekProvider,
    *,
    weather_fn: Callable = _default_weather,
    search_pois_fn: Callable = _default_search_pois,
    normalize_region_fn: Callable = _default_normalize_region,
    search_attractions_fn: Callable = _amap_service.search_attractions,
) -> dict:
    events.publish({"type": "agent_status", "data": {"agent": "researcher", "status": "start"}})
    profile: dict = state.get("profile", {})
    destination = str(profile.get("destination", "") or "")
    province, city = normalize_region_fn(destination)
    if province is None:
        events.publish({"type": "agent_status", "data": {"agent": "researcher", "status": "done"}})
        return {"candidates": [], "weather": [], "region_resolved": False}

    prefs = " ".join(profile.get("preferences", []))
    # 高德真实景点优先（用户提到城市时）；失败/无结果/无 key → RAG 三级粒度兜底
    amap_candidates: list[dict] = []
    if city:
        try:
            amap_candidates = list(search_attractions_fn(city))
        except Exception:
            amap_candidates = []  # 注入实现异常不拖垮链路
    candidates = amap_candidates or search_pois_fn(destination, query=prefs or None, k=8)

    if candidates:
        if amap_candidates:
            _enrich_amap_candidates(candidates, llm, prefs)
        else:
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
            except (AssertionError, ValueError, KeyError, TypeError, RuntimeError):
                recs = {}
            reasons = {r.get("poi_id"): str(r.get("reason", "")) for r in (recs.get("recommendations") or []) if isinstance(r, dict)}
            for p in candidates:
                p["reason"] = reasons.get(p["poi_id"], "")

    lat, lng = (float(candidates[0]["lat"]), float(candidates[0]["lng"])) if candidates else city_coord(province, None)
    weather = weather_fn(lat, lng, days=profile.get("duration_days", 3))
    events.publish({"type": "agent_status", "data": {"agent": "researcher", "status": "done"}})
    return {"candidates": candidates, "weather": weather, "region_resolved": True}
