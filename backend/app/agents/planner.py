"""Planner 行程规划师：候选景点（Researcher 产出）+ 预算约束（Budget 产出）+ 天气 → 天级行程。

LLM 只产出结构化 JSON（days[] 引用候选 poi_id），回复文本由 format_itinerary
确定性生成 —— 遵循 spec 风险对策"结构化状态，减少自由文本流转"。
候选/预算/天气全部来自 state（candidates / budget_plan / weather），
无依赖注入点；region_resolved=False（未知区域）时直接输出降级提示。
"""
from __future__ import annotations

import json

from app import events
from app.itinerary import enrich_itinerary
from app.llm.deepseek import DeepSeekProvider

PLANNER_SYSTEM_PROMPT = """你是智能旅行助手的"行程规划师"。根据用户画像、候选景点、预算约束与天气，生成逐日行程。
只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{
  "days": [
    {
      "day": 1,
      "title": "当日主题，如 广州地标与珠江夜景",
      "weather_note": "当日天气一句话，如 晴 24°C",
      "items": [
        {"time": "09:00", "name": "景点名", "poi_id": "候选列表中的景点 id（景点必须引用）", "note": "为什么去/怎么玩，10-20 字"},
        {"time": "12:30", "name": "餐厅名（示例）", "note": "午餐（示例数据，由你基于常识生成）"}
      ]
    }
  ],
  "summary": "整体行程总结，50 字以内",
  "warnings": ["提示，如 需要提前预约/雨天备选，没有则为空数组"]
}
规则：
- 每天 3-5 项，时间从早到晚；餐饮穿插在景点之间，每天 1-2 餐
- 景点必须从候选景点中选取并引用其 poi_id，不要编造景点
- 每天必须至少安排 1-2 个候选景点并引用其 poi_id（不得将所有条目都标注（示例））；只有餐厅/酒店/购物点等非景点条目才允许标注（示例）且不带 poi_id
- 酒店与餐厅是示例数据：由你基于目的地常识生成名称，名称后标注（示例），不要填 poi_id
- 住宿按预算约束的每晚住宿预算选档位
- 雨天（condition 含 雨/雪/雷）优先安排室内景点
- 尊重用户偏好标签（美食/购物/文化/自然/亲子），缺偏好时均衡安排
- 天数以 duration_days 为准，不要多排"""


def build_candidate_context(candidates: list[dict]) -> str:
    """把 Researcher 产出的候选景点（POI + 推荐理由）拼成 LLM 上下文。"""
    lines = ["候选景点（必须从中选景点并引用 poi_id）:"]
    for p in candidates:
        reason = f"，推荐理由：{p['reason']}" if p.get("reason") else ""
        lines.append(f"- {p['name']}（{p['city']}，评分{p['rating']}，价位档{p['price_tier']}）: {p['description']}{reason}")
    return "\n".join(lines) if lines else "（无候选景点）"


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


def _clean_itinerary(itinerary: dict, candidate_ids: set) -> None:
    """幻觉清洗：有 poi_id 且不在候选集合 → 丢弃；无 poi_id → 保留（示例餐饮/住宿）。"""
    for day in itinerary.get("days") or []:
        kept = []
        for item in day.get("items", []):
            pid = item.get("poi_id")
            if pid is not None and pid not in candidate_ids:
                continue  # 编造的 POI 直接丢弃
            kept.append(item)
        day["items"] = kept


def _has_candidate_reference(itinerary: dict) -> bool:
    """行程中是否存在至少一个引用候选 poi_id 的条目（无引用 = 地图空图）。"""
    return any(
        item.get("poi_id") is not None
        for day in itinerary.get("days") or []
        for item in day.get("items", [])
    )


def planner_node(state: dict, llm: DeepSeekProvider) -> dict:
    """消费 state（candidates/budget_plan/weather）→ LLM 行程 JSON → 幻觉清洗 → 回复。

    region_resolved=False（Researcher 归一化失败）时直接输出降级提示，不调用 LLM
    （图装配中该分支直接 END，不经 supervisor）；region_resolved=True 但 candidates
    为空（KB 空/未入库）同样降级输出提示，不调用 LLM，防编造景点渲染成真实行程。
    """
    events.publish({"type": "agent_status", "data": {"agent": "planner", "status": "start"}})
    profile: dict = state.get("profile", {})
    region_resolved = state.get("region_resolved")
    if region_resolved is False:
        destination = str(profile.get("destination") or "空")
        events.publish({"type": "agent_status", "data": {"agent": "planner", "status": "done"}})
        return {
            "phase": "answered",
            "itinerary": {},
            "last_reply": (
                f"目前暂不支持「{destination}」的行程规划，当前支持全国 34 个省级行政区的著名景点。"
                "可尝试输入所在省份名，如「广东」。"
            ),
        }

    candidates: list[dict] = state.get("candidates", [])
    if region_resolved is True and not candidates:
        # KB 为空/未入库：researcher 已归一化区域但无候选 → 降级提示，不调用 LLM
        # （否则 LLM 会编造景点，幻觉清洗保留无 poi_id 条目，渲染成貌似真实的行程）
        events.publish({"type": "agent_status", "data": {"agent": "planner", "status": "done"}})
        return {
            "phase": "answered",
            "itinerary": {},
            "last_reply": (
                "该区域暂未检索到景点数据，请先运行语料生成与入库"
                "（python -m app.rag.generate / python -m app.rag.ingest）。"
            ),
        }
    budget_plan: dict = state.get("budget_plan", {})
    weather: list[dict] = state.get("weather", [])

    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"{build_candidate_context(candidates)}\n"
            f"预算约束：{json.dumps((budget_plan or {}).get('items', []), ensure_ascii=False)}\n"
            f"未来 {len(weather)} 天天气：{json.dumps(weather, ensure_ascii=False)}\n"
            "请按 schema 输出行程 JSON（标记词：行程规划JSON），景点条目必须引用候选 POI 的 poi_id。"
        )},
    ]
    candidate_ids = {p.get("poi_id") for p in candidates if p.get("poi_id")}
    itinerary = {}
    for attempt in range(2):
        try:
            itinerary = llm.chat_json(messages)
        except (AssertionError, ValueError, KeyError, TypeError, RuntimeError):
            itinerary = {}
            break  # LLM 异常走既有降级路径（days-None 分支）
        _clean_itinerary(itinerary, candidate_ids)
        if not itinerary.get("days") or _has_candidate_reference(itinerary):
            break
        # 零引用兜底：追加纠正指令重试一次（无引用 = 地图空图，M5 冒烟实证 LLM 会
        # 把所有条目标（示例）规避引用规则）
        messages.append({"role": "user", "content": (
            "上一版行程没有引用任何候选景点的 poi_id，违反规则（每天至少 1-2 个候选景点"
            "并引用 poi_id，仅餐厅/酒店等非景点条目可标注（示例））。请重新输出行程 JSON。"
        )})

    # 兜底：两轮 LLM 均零引用候选 → 确定性注入 top-1 候选（地图数据链保证；M5 冒烟
    # 实证真实 LLM 会连续两轮规避引用规则，纯提示词级重试不足以保证标记）
    if itinerary.get("days") and not _has_candidate_reference(itinerary) and candidates:
        top = candidates[0]
        first = itinerary["days"][0]
        injected = {"time": "09:00", "name": top["name"], "poi_id": top["poi_id"],
                    "note": "推荐安排"}
        first["items"] = [injected] + (first.get("items") or [])

    # M5：富化行程（景点条目按 poi_id 附候选坐标），供前端地图/日卡与 trip 落库
    itinerary = enrich_itinerary(itinerary, candidates)

    if itinerary.get("days") is None:
        # days: null 不做 markdown 格式化，降级为摘要回复（T8-F4 回归）
        reply = f"行程总结：{itinerary.get('summary', '')}"
    else:
        reply = format_itinerary(itinerary)
        # 仅真实行程发布 itinerary_update（降级分支无行程可发，与早退分支一致）
        events.publish({"type": "itinerary_update",
                        "data": {"status": "generated", "itinerary": itinerary}})
    events.publish({"type": "agent_status", "data": {"agent": "planner", "status": "done"}})
    return {"phase": "answered", "itinerary": itinerary, "last_reply": reply}
