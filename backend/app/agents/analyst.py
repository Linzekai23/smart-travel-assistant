"""Analyst 需求分析师：抽取出行需求、追问缺失项、构建用户画像。"""
from __future__ import annotations

import json
from typing import Any

from app import events
from app.llm.deepseek import DeepSeekProvider

ANALYST_SYSTEM_PROMPT = """你是智能旅行助手的"需求分析师"。你的任务是从用户的出行需求中抽取结构化信息。
只输出 JSON 对象（不要任何其他文字、不要 markdown），字段如下：
{
  "destination": "目的地城市（中文名，如 北京/上海/成都/西安；未知为 null）",
  "duration_days": 出行天数（整数，未知为 null）,
  "start_date": "出发日期（YYYY-MM-DD，未知为 null）",
  "budget_cny": 总预算（人民币元，整数，未知为 null）,
  "travelers": 出行人数（整数，未知为 null）,
  "preferences": ["偏好标签，如 美食/购物/文化/自然/亲子"],
  "missing": ["destination", "duration_days", "start_date", "budget_cny", "travelers", "preferences" 中当前未知的字段名]
}
"""

CORE_FIELDS = ["destination", "duration_days"]


def _last_user_message(state: dict) -> str:
    for m in reversed(state["messages"]):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


def build_question(missing: list[str]) -> str:
    """根据缺失字段生成一句中文追问。"""
    parts = []
    if "destination" in missing:
        parts.append("想去哪个城市？")
    if "duration_days" in missing:
        parts.append("打算玩几天？")
    if "start_date" in missing:
        parts.append("大概什么时候出发？")
    if "budget_cny" in missing:
        parts.append("预算大概多少？")
    if "travelers" in missing:
        parts.append("几个人一起去？")
    if "preferences" in missing:
        parts.append("有什么特别偏好吗（美食/购物/文化…）？")
    return "为了帮你规划，还需要补充一下：" + " ".join(parts) if parts else "还需要补充一些信息，请告诉我。"


def analyst_node(state: dict, llm: DeepSeekProvider) -> dict:
    """抽取需求 → 缺失核心字段则追问（phase=asking）→ 否则合入画像（phase=planning）。"""
    events.publish({"type": "agent_status", "data": {"agent": "analyst", "status": "start"}})
    profile: dict[str, Any] = dict(state.get("profile", {}))
    user_msg = _last_user_message(state)
    history = state.get("messages", [])
    llm_messages = [
        {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
        {"role": "user", "content": f"已有画像：{json.dumps(profile, ensure_ascii=False)}\n最新需求：{user_msg}\n请按 schema 输出 JSON。"},
    ]
    parsed = llm.chat_json(llm_messages)

    for field in ("destination", "duration_days", "start_date", "budget_cny", "travelers", "preferences"):
        if parsed.get(field) is not None:
            profile[field] = parsed[field]

    missing = [f for f in parsed.get("missing", []) if f in CORE_FIELDS]
    if missing:
        events.publish({"type": "agent_status", "data": {"agent": "analyst", "status": "done"}})
        return {
            "phase": "asking",
            "messages": [{"role": "assistant", "content": build_question(missing)}],
            "profile": profile,
        }
    events.publish({"type": "agent_status", "data": {"agent": "analyst", "status": "done"}})
    return {"phase": "planning", "profile": profile}
