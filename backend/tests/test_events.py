import asyncio

from app import events


def test_publish_reaches_subscriber():
    async def scenario():
        q = events.subscribe()
        try:
            events.publish({"type": "agent_status", "data": {"agent": "analyst", "status": "start"}})
            payload = await asyncio.wait_for(q.get(), timeout=1)
            assert payload["type"] == "agent_status"
        finally:
            events.unsubscribe(q)

    asyncio.run(scenario())


def test_event_stream_frames():
    async def scenario():
        # event_stream() 是惰性 async generator：subscribe() 发生在首次迭代时，
        # 必须先启动 __anext__ 让订阅建立，再 publish，否则事件会丢失。
        stream = events.event_stream()
        first = asyncio.create_task(stream.__anext__())
        await asyncio.sleep(0.05)  # 给事件循环时间执行订阅
        events.publish({"type": "agent_status", "data": {"agent": "planner", "status": "done"}})
        frame = await first
        assert frame.startswith("event: agent_status\n")
        assert 'data: {"type": "agent_status"' in frame
        assert frame.endswith("\n\n")

    asyncio.run(scenario())
