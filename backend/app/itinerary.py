"""行程富化：把 planner 产出的结构化行程与 RAG 候选（含坐标）关联。"""
from __future__ import annotations


def enrich_itinerary(itinerary: dict, candidates: list[dict]) -> dict:
    """给行程条目附加候选景点信息（lat/lng/name/category/reason/description）。

    景点条目按 poi_id 命中候选 → 附加坐标等字段（地图标记用）；
    无 poi_id 的条目（LLM 生成的示例餐饮/住宿，语料无坐标）或未命中 → 原样保留。
    非破坏性：返回新结构、不修改入参（测试 fake 常量共享嵌套 dict，原地改会串用例）。
    """
    if not itinerary.get("days"):
        # days: None 透传：planner 的 days-None 降级分支（T8-F4 回归）依赖此语义
        return dict(itinerary)
    by_id = {p.get("poi_id"): p for p in candidates if p.get("poi_id")}
    days = []
    for day in itinerary.get("days") or []:
        items = []
        for item in day.get("items", []):
            cand = by_id.get(item.get("poi_id"))
            if cand is None:
                items.append(dict(item))
                continue
            enriched = dict(item)
            for field in ("lat", "lng", "name", "category", "reason", "description"):
                if cand.get(field) is not None:
                    enriched[field] = cand[field]
            # detail 兜底：LLM 未写详细介绍（如注入兜底条目）时附候选 description
            if not enriched.get("detail") and cand.get("description"):
                enriched["detail"] = cand["description"]
            items.append(enriched)
        days.append({**day, "items": items})
    return {**itinerary, "days": days}
