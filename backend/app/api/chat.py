"""聊天 API：POST /api/chat —— 会话持久化 + 图调用 + 回复。"""
import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import db, events

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)


@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    graph = request.app.state.graph
    if graph is None:
        raise HTTPException(
            status_code=503,
            detail="DEEPSEEK_API_KEY 未配置：请在环境变量中设置后重启后端",
        )

    sid = req.session_id or db.create_session()
    db.add_message(sid, "user", req.message)
    history = db.list_messages(sid)  # [{role, content}]，含刚写入的 user 消息

    events.publish({"type": "agent_status", "data": {"agent": "supervisor", "status": "start", "detail": "开始处理"}})
    try:
        # 多轮画像延续（上次 profile 传回图）依赖 checkpointer，M4 实现；
        # M2 只传会话历史，Analyst 每轮重新抽取。
        result = await asyncio.to_thread(
            graph.invoke,
            {"messages": history, "phase": ""},
        )
    except Exception as exc:  # LLM/图异常不落库，向前端返回 502
        raise HTTPException(status_code=502, detail=f"行程规划失败: {exc}") from exc

    # 回复优先取 last_reply（Planner 产出）；Analyst 追问场景没有
    # last_reply，兜底取 messages 最后一条 assistant 内容。
    reply = result.get("last_reply")
    if reply is None and result.get("messages"):
        reply = result["messages"][-1].get("content")
    if reply is None:
        reply = "抱歉，本次没有生成回复。"
    db.add_message(sid, "assistant", reply)
    return {"session_id": sid, "reply": reply}
