"""共享测试基座：FakeProvider / FakeEmbedder / fake_weather + 常用 fixture。"""
import json
import math

import pytest


class FakeProvider:
    """按 prompt 子串匹配返回预设响应的假 LLM。

    json_responses: {prompt 子串: 返回的 dict}
    text_responses: {prompt 子串: 返回的 str}
    """

    def __init__(
        self,
        json_responses: dict[str, dict] | None = None,
        text_responses: dict[str, str] | None = None,
    ) -> None:
        self.json_responses = json_responses or {}
        self.text_responses = text_responses or {}
        self.calls: list[list[dict]] = []

    def _match(self, table: dict, messages: list[dict]) -> object | None:
        prompt = messages[-1]["content"]
        for key, resp in table.items():
            if key in prompt:
                return resp
        return None

    def chat_json(self, messages: list[dict]) -> dict:
        self.calls.append(messages)
        resp = self._match(self.json_responses, messages)
        if resp is None:
            raise AssertionError(
                f"FakeProvider 未配置该 prompt 的响应: {messages[-1]['content'][:80]}"
            )
        return dict(resp)

    def chat(self, messages: list[dict], *, json_mode: bool = False) -> str:
        # json_mode 走 chat_json（内部记录一次 calls）；此处不再重复 append，
        # 否则每次 json_mode 调用会产生 2 条 calls 记录
        if json_mode:
            return json.dumps(self.chat_json(messages), ensure_ascii=False)
        self.calls.append(messages)
        resp = self._match(self.text_responses, messages)
        if resp is None:
            raise AssertionError(
                f"FakeProvider 未配置该 prompt 的响应: {messages[-1]['content'][:80]}"
            )
        return str(resp)


class FakeEmbedder:
    """确定性伪向量：按字符累加哈希 → 512 维 → L2 归一化。

    关键性质：含相同关键词的文本向量余弦相似度更高（如查询"火锅"与
    含"火锅"的文档），使向量检索的排序可被测试断言。
    """

    DIM = 512

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.DIM
        for ch in text:
            idx = (ord(ch) * 2654435761) % self.DIM
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector("Q:" + text)


def fake_weather(lat: float, lng: float, *, days: int = 3) -> list[dict]:
    """测试用天气：确定性数据，避免天气测试访问真实 Open-Meteo。"""
    return [
        {"date": f"2026-10-{i:02d}", "t_max": 24.0, "t_min": 16.0,
         "condition": "晴", "source": "open-meteo"}
        for i in range(1, days + 1)
    ]
