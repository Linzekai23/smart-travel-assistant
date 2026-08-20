from typing import Annotated, TypedDict

import operator


class TravelState(TypedDict):
    """Agent 协作共享状态。字段更新采用 reducer 语义（见各字段注释）。"""

    messages: Annotated[list[dict], operator.add]  # 对话历史，累加
    phase: str  # ready / asking / planning / answered
    profile: dict  # 用户画像（Analyst 产出，整体覆盖）
    itinerary: dict  # 结构化行程（Planner 产出，整体覆盖）
    last_reply: str  # 最近一次助手回复文本（聊天 API 读取）

    # M3：Researcher / Budget / Supervisor 产出
    candidates: Annotated[list[dict], operator.add]  # 景点候选 + 推荐理由
    weather: list[dict]               # 逐日天气（Researcher 产出，整体覆盖）
    budget_plan: dict                 # 预算分配（Budget 产出）
    region_resolved: bool             # Researcher 归一化结果（False=未知区域）
    supervisor_summary: dict          # Supervisor 结构化汇总
