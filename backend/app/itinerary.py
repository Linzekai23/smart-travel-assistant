"""行程富化：把 planner 产出的结构化行程与 RAG 候选（含坐标）关联。"""
from __future__ import annotations


def _match_by_name(name: str, candidates: list[dict]) -> dict | None:
    """名称包含匹配：LLM 常把候选景点名微调后使用（如 都江堰景区/宽窄巷子美食街），
    却不填 poi_id。双向包含（候选名 in 条目名 或 条目名 in 候选名）且较短一方 ≥3 字
    防误配；多个候选命中时取名称最长者（最具体）。不匹配返回 None（语料没有的编造
    景点/餐厅保持原样，不硬塞介绍与图片）。"""
    if not name:
        return None
    hits = [c for c in candidates
            if c.get("name") and len(min(name, c["name"], key=len)) >= 3
            and (name in c["name"] or c["name"] in name)]
    if not hits:
        return None
    return max(hits, key=lambda c: len(c["name"]))


def enrich_itinerary(itinerary: dict, candidates: list[dict]) -> dict:
    """给行程条目附加候选景点信息（lat/lng/name/category/reason/description）。

    景点条目按 poi_id 命中候选，或名称包含匹配候选（LLM 不填 poi_id 时的兜底，
    保证所有景点都有坐标/介绍/图片）→ 附加坐标等字段（地图标记用）；
    完全未命中（示例餐饮/住宿、语料没有的编造景点）→ 原样保留。
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
                cand = _match_by_name(item.get("name"), candidates)
            if cand is None:
                items.append(dict(item))
                continue
            enriched = dict(item)
            # poi_id 一并附加（名称匹配的条目原本没有）——前端图片/地图渲染条件
            for field in ("lat", "lng", "name", "category", "reason", "description", "poi_id"):
                if cand.get(field) is not None:
                    enriched[field] = cand[field]
            # detail 兜底：LLM 未写详细介绍或写得太短（套话，如注入兜底条目）时
            # 附候选 description（语料 200-280 字具体介绍）
            if (not enriched.get("detail") or len(enriched["detail"]) < 40) and cand.get("description"):
                enriched["detail"] = cand["description"]
            items.append(enriched)
        days.append({**day, "items": items})
    return {**itinerary, "days": days}
