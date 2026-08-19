"""SSE 事件总线：asyncio.Queue 订阅-发布。

- 图节点/API 调用 publish() 发布事件（agent_status / itinerary_update）
- 每个 SSE 客户端连接时 subscribe() 一个专属队列，断开时 unsubscribe()
- event_stream() 为每个连接产出 SSE 帧；无事件时每秒产出 ping 心跳帧
- 事件 payload 统一 {"type": str, "data": {...}}；data 必须 JSON 可序列化
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

_SUBSCRIBERS: set[asyncio.Queue[dict]] = set()
_QUEUE_MAX = 200


def subscribe() -> asyncio.Queue[dict]:
    q: asyncio.Queue[dict] = asyncio.Queue(maxsize=_QUEUE_MAX)
    _SUBSCRIBERS.add(q)
    return q


def unsubscribe(q: asyncio.Queue[dict]) -> None:
    _SUBSCRIBERS.discard(q)


def publish(payload: dict) -> None:
    """向所有订阅者推送事件；队列满则丢弃该事件（不阻塞、不抛出）。"""
    for q in list(_SUBSCRIBERS):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


def _frame(event_type: str, data: dict) -> str:
    body = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
    return f"event: {event_type}\ndata: {body}\n\n"


async def event_stream() -> AsyncIterator[str]:
    """为单个 SSE 连接产出事件帧；无事件时每秒一帧 ping。"""
    q = subscribe()
    try:
        while True:
            try:
                payload = await asyncio.wait_for(q.get(), timeout=1.0)
                yield _frame(payload["type"], payload.get("data", {}))
            except asyncio.TimeoutError:
                yield _frame("ping", {"ts": time.time()})
    finally:
        unsubscribe(q)
