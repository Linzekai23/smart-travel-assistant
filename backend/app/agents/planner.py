"""Planner 行程规划师：候选景点（Researcher 产出）+ 预算约束（Budget 产出）+ 天气 → 天级行程。

LLM 只产出结构化 JSON（days[] 引用候选 poi_id），回复文本由 format_itinerary
确定性生成 —— 遵循 spec 风险对策"结构化状态，减少自由文本流转"。
候选/预算/天气全部来自 state（candidates / budget_plan / weather），
无依赖注入点；region_resolved=False（未知区域）时直接输出降级提示。
"""
from __future__ import annotations

import json
from pathlib import Path

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
        {"name": "景点名", "poi_id": "候选列表中的景点 id（景点必须引用）", "suggested_time": "建议到访时段，如 建议上午 8:00-10:00 前往 / 建议傍晚 17:00 后前往", "time_reason": "为什么建议该时段，如 清晨人少、光线好，10-20 字", "note": "为什么去/怎么玩，10-20 字", "detail": "景点详细介绍 150-250 字：历史沿革、主要看点（具体点位/分区/建筑）、门票与开放时间、建议游玩时长，信息密度高，避免套话"},
        {"name": "餐厅名（示例）", "note": "午餐（示例数据，由你基于常识生成）", "detail": "推荐美食，如 招牌：夫妻肺片、担担面，10-30 字"}
      ]
    }
  ],
  "summary": "整体行程总结，50 字以内",
  "warnings": ["提示，如 需要提前预约/雨天备选，没有则为空数组"],
  "accommodation": [{"name": "酒店名（示例）", "days": [1, 2], "location_note": "酒店所在区域/附近景点，如 锦江区，近春熙路", "commute_note": "到景点通勤，如 到当日景点约 15-30 分钟车程", "price_note": "价格档位与预算符合性，如 中档，符合预算", "detail": "酒店环境与设施介绍，如 大堂现代、带健身房与自助早餐，近地铁口，10-30 字"}]
}
规则：
- 每天 3-5 项，按游览顺序排列（建议时段由早到晚）；餐饮穿插在景点之间，每天 1-2 餐
- 只有景点条目填 suggested_time 与 time_reason（为什么建议该时段）；餐厅/酒店/购物等非景点条目不要填
- 每个景点必须填 detail（详细介绍 150-250 字，具体信息：门票、开放时间、看点分区、游玩时长）；餐厅/住宿 detail 简短（10-30 字）
- 景点必须从候选景点中选取并引用其 poi_id，不要编造景点
- 每天必须至少安排 1-2 个候选景点并引用其 poi_id（不得将所有条目都标注（示例））；只有餐厅/酒店/购物点等非景点条目才允许标注（示例）且不带 poi_id
- 酒店与餐厅是示例数据：由你基于目的地常识生成名称，名称后标注（示例），不要填 poi_id
- 住宿推荐集中安排：优先选景点集中的区域住一家、覆盖整个行程（days 列全程天数），通勤方便；仅当某天景点与主住宿区距离确实较远（如跨市郊景区）才换第 2 家并在 commute_note 说明原因；住宿按预算约束的每晚住宿预算选档位
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
            bits = []
            when = item.get("suggested_time")
            if when:
                bits.append(f"建议{when}")
            time_reason = item.get("time_reason")
            if time_reason:
                bits.append(f"理由：{time_reason}")
            note_text = item.get("note")
            if note_text:
                bits.append(note_text)
            lines.append(f"- **{name}**" + (f"（{'；'.join(bits)}）" if bits else ""))
            detail = item.get("detail")
            if detail:
                lines.append(f"> {detail}")
        lines.append("")
    for acc in itinerary.get("accommodation") or []:
        if not lines or lines[-1] != "":
            lines.append("")
        days_txt = "、".join(f"第{d}天" for d in (acc.get("days") or []))
        bits = [f"住宿：{acc.get('name', '')}"]
        if days_txt:
            bits.append(days_txt)
        for key in ("location_note", "commute_note", "price_note"):
            if acc.get(key):
                bits.append(acc[key])
        lines.append("- 🏨 " + "；".join(bits))
        if acc.get("detail"):
            lines.append(f"> {acc['detail']}")
    if itinerary.get("summary"):
        lines.append(f"**行程总结**：{itinerary['summary']}")
    for w in itinerary.get("warnings", []):
        lines.append(f"⚠️ {w}")
    return "\n".join(lines).strip()


SUPPLEMENT_PROMPT = """你是旅行信息补全助手。以下行程条目中，判断哪些是景点（景区/博物馆/公园/街区等），哪些不是（餐厅/酒店/购物等）。
只输出 JSON 对象（标记词：景点补全），schema：
{"items": [{"name": "条目原名", "is_attraction": true/false, "detail": "景点时：150-250字具体介绍：历史沿革、主要看点、门票价格与开放时间、建议游玩时长、交通提示；非景点时留空"}]}
必须覆盖列表中的每个条目。"""


def _supplement_extra_attractions(itinerary: dict, llm: DeepSeekProvider) -> None:
    """语料外景点补全：行程里没有 poi_id、未匹配候选的条目（LLM 编造/语料缺失的
    真实景点），调用一次 LLM 分类并生成具体介绍，附加 category=attraction + detail。

    结果按景点名缓存到 data/attraction_details.json（同一景点只生成一次）；
    LLM 异常/解析失败时保持原样，不阻塞行程。
    """
    extras = [it for day in itinerary.get("days") or []
              for it in day.get("items", [])
              if not it.get("poi_id") and not it.get("category")]
    if not extras:
        return
    cache = _load_detail_cache()
    todo = [it["name"] for it in extras if it["name"] not in cache]
    if todo:
        try:
            resp = llm.chat_json([
                {"role": "system", "content": SUPPLEMENT_PROMPT},
                {"role": "user", "content": f"条目列表：{json.dumps(todo, ensure_ascii=False)}。"
                                            "请按 schema 输出 JSON（标记词：景点补全）。"},
            ])
        except (AssertionError, ValueError, KeyError, TypeError, RuntimeError):
            resp = {}
        for info in (resp.get("items") or []) if isinstance(resp, dict) else []:
            if isinstance(info, dict) and info.get("is_attraction") and info.get("detail"):
                cache[info["name"]] = {"category": "attraction", "detail": info["detail"]}
        if todo:
            _save_detail_cache(cache)
    for it in extras:
        hit = cache.get(it["name"])
        if hit:
            it["category"] = hit["category"]
            it["detail"] = hit["detail"]


def _detail_cache_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "attraction_details.json"


def _load_detail_cache() -> dict:
    try:
        return json.loads(_detail_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_detail_cache(cache: dict) -> None:
    _detail_cache_path().parent.mkdir(parents=True, exist_ok=True)
    _detail_cache_path().write_text(
        json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


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
            "上一版行程没有引用任何候选景点的 poi_id，违反规则（每天必须至少安排 1-2 个"
            "候选景点并从候选列表中选择，景点条目必须填 poi_id 且严禁标注（示例），"
            "仅餐厅/酒店等非景点条目可标注（示例））。请重新输出行程 JSON，"
            "景点 detail 用 80-120 字详细介绍。"
        )})

    # 兜底：两轮 LLM 均零引用候选 → 确定性逐天注入不同的候选景点（每天一个
    # 主要景点，地图多点、detail 由 enrich 附候选 description；M5 冒烟实证真实
    # LLM 会连续两轮规避引用规则，纯提示词级重试不足以保证标记）
    if itinerary.get("days") and not _has_candidate_reference(itinerary) and candidates:
        used: set = set()
        _slots = [("上午 8:00-10:00 前往", "清晨游客较少"),
                  ("下午 14:00-16:00 前往", "午后光线好、游客相对少"),
                  ("傍晚 17:00 后前往", "避开正午人流，夜景更美")]
        for day in itinerary["days"]:
            cand = next((c for c in candidates if c.get("poi_id") and c["poi_id"] not in used), None)
            if cand is None:
                break
            used.add(cand["poi_id"])
            when, why = _slots[min(len(used) - 1, len(_slots) - 1)]
            injected = {"name": cand["name"], "poi_id": cand["poi_id"],
                        "suggested_time": when, "time_reason": why,
                        "note": "推荐安排"}
            day["items"] = [injected] + (day.get("items") or [])

    # M5：富化行程（景点条目按 poi_id 附候选坐标），供前端地图/日卡与 trip 落库
    itinerary = enrich_itinerary(itinerary, candidates)
    # 语料外景点补全：LLM 编造/语料缺失的真实景点 → LLM 生成具体介绍（缓存）
    _supplement_extra_attractions(itinerary, llm)

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
