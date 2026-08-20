"""Budget 预算官：按总预算分配类别额度，产出预算表。

LLM 只产出结构化 JSON（items）；确定性兜底保证 sum(items) <= budget_cny：
- 缩放：总超预算时等比缩放，尾差收齐
- 兜底：LLM 失败/空 items 时按固定比例分配
"""
from __future__ import annotations

from app import events
from app.llm.deepseek import DeepSeekProvider

BUDGET_CATEGORIES = ["住宿", "交通", "餐饮", "门票", "其他"]

BUDGET_SYSTEM_PROMPT = """你是智能旅行助手的"预算官"。根据用户总预算、天数与偏好，把预算分配到固定类别。
只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{"items": [
  {"category": "住宿|交通|餐饮|门票|其他", "amount": 金额整数, "note": "一句话说明，10 字内"}
]}
规则：
- 类别必须取自：住宿、交通、餐饮、门票、其他，每个类别最多一条
- 总金额不得超过预算上限；住宿占比通常 30-45%，餐饮 20-30%
- 金额用整数（元）"""

DEFAULT_WEIGHTS: list[tuple[str, float]] = [
    ("住宿", 0.40), ("交通", 0.20), ("餐饮", 0.25), ("门票", 0.15),
]


def _default_items(budget_cny: int) -> list[dict]:
    """确定性兜底分配：按固定比例，尾差归"其他"，保证 sum == budget_cny。"""
    items = []
    used = 0
    for name, weight in DEFAULT_WEIGHTS:
        amount = round(budget_cny * weight)
        items.append({"category": name, "amount": amount, "note": "默认比例分配"})
        used += amount
    items.append({"category": "其他", "amount": budget_cny - used, "note": "机动余量"})
    return items


def _clean_items(items: list, budget_cny: int) -> list[dict]:
    """清洗 LLM 输出：非法类别丢弃、金额取正整、类别去重；清洗后空 → 兜底。"""
    seen: set[str] = set()
    out: list[dict] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        category = str(it.get("category", "")).strip()
        if category not in BUDGET_CATEGORIES or category in seen:
            continue
        try:
            amount = int(it["amount"])
        except (KeyError, TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        seen.add(category)
        out.append({"category": category, "amount": amount,
                    "note": str(it.get("note", "") or "").strip()[:20]})
    return out or _default_items(budget_cny)


def _scale(items: list[dict], budget_cny: int) -> tuple[list[dict], bool]:
    """等比缩放到总和不超预算；最后一项收尾差。返回 (items, scaled)。"""
    total = sum(it["amount"] for it in items)
    if total <= budget_cny:
        return items, False
    scale = budget_cny / total
    scaled = []
    used = 0
    for i, it in enumerate(items):
        if i == len(items) - 1:
            amount = budget_cny - used  # 尾差收齐
        else:
            amount = round(it["amount"] * scale)
            used += amount
        scaled.append({"category": it["category"], "amount": amount, "note": it["note"]})
    return scaled, True


def format_budget(plan: dict) -> str:
    """预算表 markdown（确定性）；items 空返回空串。"""
    items = plan.get("items") or []
    if not items:
        return ""
    lines = ["## 预算分配", "", "| 类别 | 金额（元） | 说明 |", "|---|---|---|"]
    for it in items:
        lines.append(f"| {it['category']} | {it['amount']} | {it.get('note', '')} |")
    total = plan.get("total", sum(it["amount"] for it in items))
    mark = "（已按预算上限缩放）" if plan.get("scaled") else ""
    lines.append(f"| **合计** | **{total}** | {mark} |")
    return "\n".join(lines)


def budget_node(state: dict, llm: DeepSeekProvider) -> dict:
    events.publish({"type": "agent_status", "data": {"agent": "budget", "status": "start"}})
    profile: dict = state.get("profile", {})
    budget_cny = profile.get("budget_cny")
    if not isinstance(budget_cny, (int, float)) or budget_cny <= 0:
        events.publish({"type": "agent_status", "data": {"agent": "budget", "status": "done"}})
        return {"budget_plan": {"items": [], "total": None, "checked": False,
                                "scaled": False, "note": "未提供总预算"}}

    import json

    budget_cny = int(budget_cny)
    messages = [
        {"role": "system", "content": BUDGET_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"画像：{json.dumps(profile, ensure_ascii=False)}\n"
            f"总预算上限：{budget_cny} 元，出行 {profile.get('duration_days', 3)} 天。\n"
            "请按 schema 输出预算分配 JSON（标记词：预算分配JSON）。"
        )},
    ]
    try:
        parsed = llm.chat_json(messages)
        items = _clean_items(parsed.get("items"), budget_cny)
    except (AssertionError, ValueError, KeyError, TypeError):
        items = _default_items(budget_cny)

    items, scaled = _scale(items, budget_cny)
    events.publish({"type": "agent_status", "data": {"agent": "budget", "status": "done"}})
    return {"budget_plan": {
        "items": items,
        "total": sum(it["amount"] for it in items),
        "checked": True, "scaled": scaled,
    }}
