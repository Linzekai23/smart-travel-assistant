import asyncio
import json
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()


@router.get("/api/events")
async def events():
    async def gen():
        try:
            while True:
                payload = {"type": "ping", "ts": time.time()}
                yield f"event: ping\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(gen(), media_type="text/event-stream")
