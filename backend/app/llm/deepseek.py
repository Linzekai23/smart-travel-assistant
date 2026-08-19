"""DeepSeek（OpenAI 兼容）Provider 层。

环境变量：
- DEEPSEEK_API_KEY  必填，缺失时 get_provider() 抛 RuntimeError
- DEEPSEEK_BASE_URL 默认 https://api.deepseek.com
- DEEPSEEK_MODEL    默认 deepseek-chat

测试注入：DeepSeekProvider(client=...) 传入 httpx.Client（如 MockTransport），
生产默认 httpx.Client(timeout=60)。
"""
import json
import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
CHAT_PATH = "/chat/completions"

_provider: "DeepSeekProvider | None" = None


class DeepSeekProvider:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = client or httpx.Client(timeout=60)

    def _request(self, messages: list[dict], json_mode: bool) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.6,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            resp = self._client.post(
                f"{self.base_url}{CHAT_PATH}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"DeepSeek 请求失败: {exc}") from exc
        if resp.status_code != 200:
            raise RuntimeError(
                f"DeepSeek 返回 {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def chat(self, messages: list[dict], *, json_mode: bool = False) -> str:
        return self._request(messages, json_mode=json_mode)

    def chat_json(self, messages: list[dict]) -> dict:
        """JSON 模式调用并解析；DeepSeek 要求提示词中包含 json 字样。"""
        content = self._request(messages, json_mode=True)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"DeepSeek 返回非法 JSON: {content[:200]}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"DeepSeek JSON 不是对象: {content[:200]}")
        return parsed


def get_provider() -> DeepSeekProvider:
    """模块级惰性单例；DEEPSEEK_API_KEY 缺失时抛 RuntimeError。"""
    global _provider
    if _provider is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "缺少环境变量 DEEPSEEK_API_KEY（DeepSeek 平台申请后配置）"
            )
        _provider = DeepSeekProvider(
            api_key=api_key,
            base_url=os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
            model=os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL),
        )
    return _provider
