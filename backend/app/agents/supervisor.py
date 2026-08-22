"""Supervisor 主管：LLM 结构化汇总（summary/tips）+ 确定性拼装最终回复。

LLM 只产出结构化 JSON；last_reply 由 format_supervisor_reply 确定性生成
（行程 markdown + 预算表 markdown + 总体建议 + 提示），遵循 spec 风险对策。
"""
from __future__ import annotations

import json

from app import events
from app.agents.budget import format_budget
from app.agents.planner import format_itinerary
from app.llm.deepseek import DeepSeekProvider

SUPERVISOR_SYSTEM_PROMPT = """你是智能旅行助手的"主管"。查看行程、预算、天气与用户画像，输出整体总结与建议。
只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{"summary": "对行程和预算的整体评价与建议，50 字以内", "tips": ["提示数组，每条 20 字以内，如 天气提醒/预算提醒/预约提醒"]}
规则：
- summary 客观精炼，不要重复行程细节
- tips 1-3 条，优先天气与预算相关"""


def format_supervisor_reply(
    itinerary: dict,
    budget_plan: dict,
    weather: list[dict],
    summary: str = "",
    tips: list[str] | None = None,
) -> str:
    """确定性拼装最终回复：行程 + 预算表 + 总体建议 + 提示 + 天气脚注。"""
    parts = [format_itinerary(itinerary)]
    budget_text = format_budget(budget_plan)
    if budget_text:
        parts.append(budget_text)
    if summary:
        parts.append(f"**总体建议**：{summary}")
    for tip in tips or []:
        if tip.strip():
            parts.append(f"💡 {tip.strip()}")
    reply = "\n\n".join(parts)
    if any(w.get("source") == "simulated" for w in weather):
        reply += "\n\n_（天气数据暂不可用，已用模拟数据，仅供参考）_"
    return reply


def supervisor_node(state: dict, llm: DeepSeekProvider) -> dict:
    events.publish({"type": "agent_status", "data": {"agent": "supervisor", "status": "start"}})
    summary, tips = "", []
    try:
        messages = [
            {"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"画像：{json.dumps(state.get('profile', {}), ensure_ascii=False)}\n"
                f"行程：{json.dumps(state.get('itinerary', {}), ensure_ascii=False)}\n"
                f"预算：{json.dumps(state.get('budget_plan', {}), ensure_ascii=False)}\n"
                f"天气：{json.dumps(state.get('weather', []), ensure_ascii=False)}\n"
                "请按 schema 输出汇总 JSON（标记词：汇总JSON）。"
            )},
        ]
        parsed = llm.chat_json(messages)
        summary = str(parsed.get("summary") or "")[:200].strip()
        # 非字符串元素（如 LLM 返回的 null/数字）直接丢弃，防渲染出「💡 None」
        tips = [
            str(t).strip()[:100]
            for t in (parsed.get("tips") or [])
            if isinstance(t, str) and t.strip()
        ][:5]
    except (AssertionError, ValueError, KeyError, TypeError, RuntimeError):
        summary, tips = "", []  # LLM 失败 → 确定性兜底拼装

    reply = format_supervisor_reply(
        state.get("itinerary", {}),
        state.get("budget_plan", {}),
        state.get("weather", []),
        summary, tips,
    )
    events.publish({"type": "agent_status", "data": {"agent": "supervisor", "status": "done"}})
    return {"supervisor_summary": {"summary": summary, "tips": tips},
            "last_reply": reply, "phase": "answered"}
