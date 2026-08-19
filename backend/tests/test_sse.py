import asyncio
import contextlib
import json

from app.main import app


def _scope() -> dict:
    """Minimal ASGI HTTP scope for GET /api/events.

    spec_version >= 2.4 makes Starlette's StreamingResponse take the simple
    path (stream the body without spawning a `listen_for_disconnect` task),
    which keeps this test deterministic.
    """
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/events",
        "raw_path": b"/api/events",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }


def test_sse_emits_ping_events():
    async def run() -> None:
        sent: list[dict] = []
        start_seen = asyncio.Event()
        body_seen = asyncio.Event()

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            sent.append(message)
            if message["type"] == "http.response.start":
                start_seen.set()
            elif message["type"] == "http.response.body":
                body_seen.set()

        task = asyncio.create_task(app(_scope(), receive, send))
        try:
            # First the response start message: 200 + text/event-stream.
            await asyncio.wait_for(start_seen.wait(), timeout=5)
            start = next(m for m in sent if m["type"] == "http.response.start")
            assert start["status"] == 200
            headers = {k.decode(): v.decode() for k, v in start["headers"]}
            assert headers["content-type"].startswith("text/event-stream")

            # Then the first SSE event chunk.
            await asyncio.wait_for(body_seen.wait(), timeout=5)
            chunk = next(
                m["body"].decode()
                for m in sent
                if m["type"] == "http.response.body" and m["body"]
            )
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # SSE framing: "event: ping" + "data: <json>" terminated by a blank line.
        assert chunk.endswith("\n\n")
        lines = chunk.split("\n")
        assert lines[0] == "event: ping"
        assert lines[1].startswith("data: ")
        payload = json.loads(lines[1].split("data: ", 1)[1])
        assert payload["type"] == "ping"
        assert isinstance(payload["ts"], float)

    asyncio.run(run())
