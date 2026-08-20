"""SSE 事件总线：asyncio.Queue 订阅-发布。

- 图节点（在 asyncio.to_thread 的 worker 线程中运行）/API 调用 publish()
  发布事件（agent_status / itinerary_update）；publish 经 call_soon_threadsafe
  投递到订阅者的事件循环，跨线程安全
- 每个 SSE 客户端连接时 subscribe() 一个专属队列，断开时 unsubscribe()
- event_stream() 为每个连接产出 SSE 帧；无事件时每秒产出 ping 心跳帧
- 事件 payload 统一 {"type": str, "data": {...}}；data 必须 JSON 可序列化
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

_SUBSCRIBERS: set[tuple[asyncio.Queue[dict], asyncio.AbstractEventLoop | None]] = set()
_QUEUE_MAX = 200


def subscribe() -> asyncio.Queue[dict]:
    q: asyncio.Queue[dict] = asyncio.Queue(maxsize=_QUEUE_MAX)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None  # 无运行中事件循环（如测试的同步上下文）：publish 直接入队
    _SUBSCRIBERS.add((q, loop))
    return q


def unsubscribe(q: asyncio.Queue[dict]) -> None:
    for entry in list(_SUBSCRIBERS):
        if entry[0] is q:
            _SUBSCRIBERS.discard(entry)
            break


def _put(q: asyncio.Queue[dict], payload: dict) -> None:
    try:
        q.put_nowait(payload)
    except asyncio.QueueFull:
        pass  # 队列满则丢弃（不阻塞、不抛出）——语义不变


def publish(payload: dict) -> None:
    """向所有订阅者推送事件；可能从 worker 线程调用（图节点在 to_thread 中运行）。

    经 call_soon_threadsafe 投递到订阅者的事件循环，避免跨线程触碰 Queue；
    无事件循环的订阅者（subscribe 时无运行中 loop，仅同步测试上下文）直接入队。"""
    for q, loop in list(_SUBSCRIBERS):
        if loop is None:
            _put(q, payload)
            continue
        loop.call_soon_threadsafe(_put, q, payload)


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
