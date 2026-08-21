"""聊天 API：POST /api/chat —— 会话持久化 + 图调用 + 回复（含 trip 载荷）；
GET /api/chat/history —— 历史恢复；GET /api/itinerary —— 最新结构化行程。"""
import asyncio
import json
import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel, Field

from app import db, events  # noqa: F401  # events 保持导入（graph 节点经 events 发布）
from app.graph import build_graph

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)


def _new_checkpointer() -> SqliteSaver:
    """每次请求新建 SqliteSaver（独立 sqlite 连接，asyncio.to_thread 线程池下不跨线程共享）。"""
    path = Path(os.environ.get("TRAVEL_DB_PATH", "data/travel.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def _graph_for_request(request: Request):
    """每请求构建带 checkpointer 的图实例（图装配开销 ≪ LLM 调用）。"""
    provider = request.app.state.provider
    return build_graph(provider, checkpointer=_new_checkpointer())


def _build_trip(result: dict) -> dict | None:
    """组装前端 trip 载荷：结构化行程 + 预算 + 汇总建议。

    追问轮/降级回复（无 itinerary 或 days 为空）→ None，前端回退纯文本渲染。
    """
    itinerary = result.get("itinerary")
    if not itinerary or not itinerary.get("days"):
        return None
    summary = result.get("supervisor_summary") or {}
    return {
        "itinerary": itinerary,
        "budget_plan": result.get("budget_plan") or {},
        "summary": summary.get("summary") or "",
        "tips": summary.get("tips") or [],
    }


@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    provider = request.app.state.provider
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail="DEEPSEEK_API_KEY 未配置：请在环境变量中设置后重启后端",
        )

    sid = req.session_id or db.create_session()
    if db.get_session(sid) is None:
        # 非法/未知 session_id：换新会话处理（checkpoint 无记录，按新 thread 开始）
        sid = db.create_session()
    db.add_message(sid, "user", req.message)

    try:
        graph = _graph_for_request(request)
        # M4：checkpointer 按 thread_id=session_id 恢复旧 state（画像/行程/消息）；
        # 初始输入只含最新一条 user 消息，绝不传全量历史（operator.add 会重复累积）。
        result = await asyncio.to_thread(
            graph.invoke,
            {"messages": [{"role": "user", "content": req.message}], "phase": ""},
            config={"configurable": {"thread_id": sid}},
        )
    except Exception as exc:  # LLM/图异常不落库，向前端返回 502
        raise HTTPException(status_code=502, detail=f"行程规划失败: {exc}") from exc

    reply = result.get("last_reply")
    if reply is None and result.get("messages"):
        reply = result["messages"][-1].get("content")
    if reply is None:
        reply = "抱歉，本次没有生成回复。"
    trip = _build_trip(result)
    db.add_message(
        sid, "assistant", reply,
        trip_json=json.dumps(trip, ensure_ascii=False) if trip else None,
    )
    return {"session_id": sid, "reply": reply, "trip": trip}


@router.get("/api/chat/history")
async def history(session_id: str):
    if db.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "messages": db.list_messages(session_id)}


@router.get("/api/itinerary")
async def itinerary(session_id: str):
    """最新一条结构化行程（刷新后恢复地图/日卡）；无会话或无行程 → 404。"""
    if db.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    trip = db.get_latest_trip(session_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="该会话暂无行程")
    return {"session_id": session_id, "trip": trip}
