import json

import pytest
import httpx
from httpx import MockTransport

from app.llm import deepseek


def _client_for(payload: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=MockTransport(handler))


def test_chat_returns_content():
    fake = _client_for({"choices": [{"message": {"content": "你好"}}]})
    provider = deepseek.DeepSeekProvider(api_key="test-key", client=fake)
    out = provider.chat([{"role": "user", "content": "hi"}])
    assert out == "你好"


def test_chat_json_sends_json_mode_and_parses():
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["body"] = request.read()
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}
        )

    fake = httpx.Client(transport=MockTransport(handler))
    provider = deepseek.DeepSeekProvider(api_key="test-key", client=fake)
    out = provider.chat_json([{"role": "user", "content": "hi"}])
    assert out == {"ok": True}
    body = json.loads(sent["body"])
    assert body["response_format"] == {"type": "json_object"}
    assert body["model"] == "deepseek-chat"


def test_chat_json_raises_on_invalid_json():
    fake = _client_for({"choices": [{"message": {"content": "not-json"}}]})
    provider = deepseek.DeepSeekProvider(api_key="test-key", client=fake)
    with pytest.raises(ValueError, match="JSON"):
        provider.chat_json([{"role": "user", "content": "hi"}])


def test_provider_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    fake = httpx.Client(transport=MockTransport(handler))
    provider = deepseek.DeepSeekProvider(api_key="test-key", client=fake)
    with pytest.raises(RuntimeError, match="500"):
        provider.chat([{"role": "user", "content": "hi"}])


def test_get_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        deepseek.get_provider()
