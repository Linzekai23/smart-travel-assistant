from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app import events

router = APIRouter()


@router.get("/api/events")
async def events_endpoint():
    """SSE 事件流：ping 心跳 + agent_status/itinerary_update 事件。"""
    return StreamingResponse(events.event_stream(), media_type="text/event-stream")
