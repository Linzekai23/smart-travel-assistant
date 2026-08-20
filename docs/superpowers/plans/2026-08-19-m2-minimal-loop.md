# M2 最小闭环实现计划（DeepSeek Provider + RAG POI 知识库 + Analyst/Planner + 天气）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 "10月去成都玩3天，预算8000，喜欢美食" 经 Analyst（需求补全）→ Planner（行程生成）两个 Agent 协作，返回一份可用简单行程。POI 数据来自 **RAG 知识库**（Chroma + BGE，全国约 20 城景点/酒店/餐厅，DeepSeek 自举生成语料）。

**Architecture:** 在 M1 的 LangGraph 空图上挂两个真实节点。Analyst 用 DeepSeek（JSON 模式）抽取需求画像并追问缺失项；Planner 从 RAG 知识库语义检索候选 POI（景点 + 周边餐厅 + 酒店），LLM 只产出结构化行程 JSON，再由确定性格式化函数转成中文回复文本。SSE 端点从纯 ping 升级为事件总线（asyncio.Queue 订阅-发布）。**RAG 检索层提供与模拟库相同的注入接口（search_pois/get_poi/normalize_city + search_nearby），Planner 与图装配无需感知检索实现。**

**Tech Stack:** Python 3.11+（venv 实测 3.14.6）· FastAPI 0.141 · LangGraph 1.2 · httpx 0.28 · SQLite（M1 已有）；DeepSeek（OpenAI 兼容，JSON 模式）；**Chroma 1.5 + BGE（bge-small-zh-v1.5，512 维，ModelScope 下载）+ transformers**；Open-Meteo 免 key 天气；React 19 + Vite 8 + Tailwind v4（M1 已有）。

**Spec:** [docs/superpowers/specs/2026-08-19-travel-assistant-design.md](../../specs/2026-08-19-travel-assistant-design.md)（§3 Agent 划分 5 个、§5 功能需求 1/3/4/5、§6 里程碑 M2 —— 已修订：RAG POI 知识库、国内城市）

**前置条件：** PR #1（M1）已合并；当前分支 `feat/m2-minimal-loop`（已从 origin/main 创建）。

## Global Constraints

- 开发平台：Windows 11（Git Bash），后端 venv 用 `.venv/Scripts/python`（Windows）路径调用
- 后端端口 `8000`，前端端口 `5173`，前端通过 Vite proxy 转发 `/api` → `http://localhost:8000`（避免 CORS）
- UI 文案与 LLM 提示词、回复文本使用简体中文；**示例城市一律国内（演示文案统一"10月去成都玩3天，预算8000，喜欢美食"）**
- **新依赖（加入 pyproject dependencies）**：httpx>=0.27（从 dev 移入）、chromadb>=1.5、transformers>=4.44、torch>=2.2（PyPI Windows 默认 CPU 版）、sentencepiece>=0.2、modelscope>=1.15；dev 仅 pytest
- **模型必须从 ModelScope 下载**（实测 huggingface.co 与 hf-mirror.com 均不可达）；下载后本地缓存离线加载
- **测试一律不访问真实网络、不加载真实模型**：LLM 用 FakeProvider、天气用 fake_weather、embedding 用 FakeEmbedder、Chroma 用 tmp_path 持久化目录；只有 Task 4 的手动冒烟步骤与 Task 10 的手动演示才使用真实 DeepSeek Key、真实 BGE 模型与真实天气 API
- 运行时读取环境变量：`DEEPSEEK_API_KEY`（必填，缺失时应用仍可启动、聊天接口返回 503）、`DEEPSEEK_BASE_URL`（默认 `https://api.deepseek.com`）、`DEEPSEEK_MODEL`（默认 `deepseek-chat`）、`TRAVEL_DB_PATH`（M1）、`RAG_MODEL_DIR`（默认 `backend/data/bge-model`）、`CHROMA_PERSIST_DIR`（默认 `backend/data/chroma`）、`POI_CORPUS_PATH`（默认 `backend/data/poi_corpus.jsonl`）
- **`backend/data/` 全部入 .gitignore**（chroma 库、语料、模型缓存都不提交）
- 每任务结束必须提交（frequent commits），commit 信息以 `Co-Authored-By: Claude <noreply@anthropic.com>` 结尾
- 语料数据标注为 **"AI 生成示例数据，坐标仅供参考"**（generate.py 的 prompt 与 README 都注明）

## 文件结构（M2 后）

```
backend/
├── app/
│   ├── agents/
│   │   ├── __init__.py        # 空
│   │   ├── analyst.py         # Task 7：需求分析师节点
│   │   └── planner.py         # Task 8：行程规划师节点
│   ├── api/
│   │   ├── sse.py             # Task 9 重构：走事件总线
│   │   └── chat.py            # Task 9：POST /api/chat
│   ├── llm/
│   │   ├── __init__.py        # 空
│   │   └── deepseek.py        # Task 1：DeepSeek Provider
│   ├── rag/
│   │   ├── __init__.py        # 空
│   │   ├── embeddings.py      # Task 2：BGE 封装（ModelScope 下载 + CLS pooling + query 指令）
│   │   ├── download_model.py  # Task 2：模型下载脚本（python -m app.rag.download_model）
│   │   ├── vector_store.py    # Task 3：Chroma 封装
│   │   ├── generate.py        # Task 4：语料生成（DeepSeek 一次一城，JSON 模式）
│   │   └── ingest.py          # Task 4：校验 + poi_id + 入库（python -m app.rag.ingest）
│   ├── tools/
│   │   ├── __init__.py        # 空
│   │   └── weather_api.py     # Task 6：天气适配器
│   ├── events.py              # Task 9：SSE 事件总线
│   ├── graph.py               # Task 9：双节点图 + 条件路由（移除 M1 stub）
│   ├── state.py               # Task 9：扩展 TravelState
│   ├── db.py                  # M1 已有，不动
│   └── main.py                # Task 9：lifespan + chat 路由
├── tests/
│   ├── conftest.py            # Task 2：FakeProvider/FakeEmbedder/fake_weather + fixtures
│   ├── fixtures/
│   │   └── sample_pois.jsonl  # Task 5：检索器测试用少量样本语料
│   ├── test_health.py / test_sse.py / test_db.py   # M1 已有；test_sse.py Task 9 补充+更新断言
│   ├── test_deepseek.py       # Task 1
│   ├── test_embeddings.py     # Task 2
│   ├── test_vector_store.py   # Task 3
│   ├── test_generate.py       # Task 4
│   ├── test_ingest.py         # Task 4
│   ├── test_weather_api.py    # Task 6
│   ├── test_analyst.py        # Task 7
│   ├── test_planner.py        # Task 8
│   ├── test_events.py         # Task 9
│   ├── test_graph.py          # Task 9 整体重写
│   └── test_chat.py           # Task 9

frontend/src/
├── api/sse.ts                 # Task 10：ProcessEvent 判别联合
├── components/
│   ├── AgentProcessPanel.tsx  # Task 10：agent_status 中文渲染
│   └── ChatPanel.tsx          # Task 10：onSend 接线
└── App.tsx                    # Task 10：消息发送/回复展示
```

## 跨任务接口契约（后写任务依赖前写任务，签名必须逐字一致）

| 生产者 | 接口 |
|---|---|
| Task 1 | `DeepSeekProvider.chat(messages: list[dict], *, json_mode: bool = False) -> str`；`DeepSeekProvider.chat_json(messages: list[dict]) -> dict`；`get_provider() -> DeepSeekProvider` |
| Task 2 | `Embedder.embed(texts: list[str]) -> list[list[float]]`（512 维，L2 归一化）；`Embedder.embed_query(text: str) -> list[float]`（带 BGE 查询指令）；`FakeEmbedder`（tests/conftest.py，字符累加哈希向量，同关键词文本向量相近）；`MODEL_ID = "BAAI/bge-small-zh-v1.5"` |
| Task 3 | `VectorStore(persist_dir: str, embedder)`；`VectorStore.upsert_pois(pois: list[dict]) -> int`；`VectorStore.query(text: str, *, city: str \| None = None, category: str \| None = None, k: int = 10) -> list[dict]`（text 为空 → metadata 过滤 + rating 降序）；`VectorStore.get_all(city=None, category=None) -> list[dict]`；`VectorStore.count() -> int`；返回的 POI dict 字段：`{poi_id, city, name, category, rating, price_tier, lat, lng, description, tags}` |
| Task 4 | `CITIES: list[str]`（20 城）、`CITY_EN: dict[str, str]`、`CITY_COORDS: dict[str, tuple[float, float]]`（城市中心，坐标校验用）；`generate_city(provider, city) -> list[dict]`；`validate_pois(city, pois) -> list[dict]`（字段/类别/坐标 ±2° 校验，越界丢弃）；`load_corpus(jsonl_path) -> list[dict]`（生成 poi_id=`{CITY_EN[city]}-{序号:03d}`）；`run_ingest(jsonl_path, store) -> int` |
| Task 5 | `normalize_city(name) -> str \| None`（20 城中文/拼音别名）；`search_pois(city, *, category=None, query=None, k=10) -> list[dict]`；`get_poi(poi_id) -> dict \| None`；`search_nearby(lat, lng, *, category=None, radius_km=3.0, k=5) -> list[dict]`（haversine 距离升序）；`get_store() -> VectorStore`（惰性单例，CHROMA_PERSIST_DIR + 真实 BGE）；`set_store(store)`（测试注入） |
| Task 6 | `get_weather(lat, lng, *, days=5, client=None) -> list[dict]`（source ∈ {"open-meteo","simulated"}） |
| Task 7 | `analyst_node(state, llm) -> dict`；`build_question(missing) -> str` |
| Task 8 | `planner_node(state, llm, *, weather_fn, search_pois_fn, search_nearby_fn, get_poi_fn, normalize_city_fn) -> dict`；`format_itinerary(itinerary) -> str`；`build_candidate_context(profile, search_pois_fn, search_nearby_fn) -> str` |
| Task 9 | `events.subscribe/unsubscribe/publish/event_stream`；`build_graph(llm_provider, *, weather_fn, search_pois_fn, search_nearby_fn, get_poi_fn, normalize_city_fn) -> CompiledStateGraph`；`POST /api/chat`；TravelState 五字段 |
| Task 10 | `ProcessEvent` 判别联合；`ChatPanel` props `{onSend, disabled?}`；`App.tsx` session_id 续接 |

---

### Task 1: DeepSeek Provider 层

**Files:**
- Create: `backend/app/llm/__init__.py`（空）
- Create: `backend/app/llm/deepseek.py`
- Create: `backend/.env.example`
- Modify: `backend/pyproject.toml`（httpx 移入 dependencies）
- Test: `backend/tests/test_deepseek.py`

**Interfaces:**
- Produces: `DeepSeekProvider`（chat / chat_json）、`get_provider()`、`DEFAULT_BASE_URL`、`DEFAULT_MODEL`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_deepseek.py`：
```python
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
```
预期：FAIL —— `ModuleNotFoundError: No module named 'app.llm'`。

- [ ] **Step 2: 实现 Provider**

`backend/app/llm/deepseek.py`：
```python
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
```

`backend/.env.example`：
```
# 复制为 backend/.env 或配置到系统环境变量（本项目后端不自动加载 .env，
# 由启动命令或 IDE 注入）
DEEPSEEK_API_KEY=sk-your-deepseek-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# RAG 知识库（可选，有默认值）
# RAG_MODEL_DIR=backend/data/bge-model
# CHROMA_PERSIST_DIR=backend/data/chroma
# POI_CORPUS_PATH=backend/data/poi_corpus.jsonl
```

`backend/pyproject.toml`（httpx 移入 dependencies，dev 只剩 pytest）：
```toml
[project]
# ...其余不变...
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "langgraph>=0.2",
    "pydantic>=2.7",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]
```
（只改这两处，其余保持现状。）

- [ ] **Step 3: 运行测试验证通过**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_deepseek.py -v`
预期：5 passed。再跑全量：`pytest -v` → 11 passed。

- [ ] **Step 4: 提交**

```bash
cd /d/agent
git add backend/
git commit -m "feat(backend): DeepSeek Provider 层（httpx + JSON 模式）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: BGE Embedding 层（ModelScope 下载 + 本地加载）

**Files:**
- Create: `backend/app/rag/__init__.py`（空）
- Create: `backend/app/rag/embeddings.py`
- Create: `backend/app/rag/download_model.py`
- Modify: `backend/pyproject.toml`（RAG 依赖）
- Create: `backend/tests/conftest.py`（FakeProvider + FakeEmbedder + fake_weather，后续任务共用）
- Test: `backend/tests/test_embeddings.py`

**Interfaces:**
- Produces: `Embedder`（embed / embed_query）、`MODEL_ID`；conftest 的 `FakeEmbedder`、`fake_weather`

**注意：** 模型只做下载脚本与惰性加载，**测试不加载真实模型**（FakeEmbedder 替代）。真实模型下载 + 加载冒烟放在 Task 4 手动步骤。

- [ ] **Step 1: 写失败测试**

`backend/tests/conftest.py`：
```python
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
        self.calls.append(messages)
        if json_mode:
            return json.dumps(self.chat_json(messages), ensure_ascii=False)
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
```

`backend/tests/test_embeddings.py`：
```python
import math

from conftest import FakeEmbedder


def test_fake_embedder_dimension_and_norm():
    out = FakeEmbedder().embed(["你好"])
    assert len(out) == 1
    assert len(out[0]) == 512
    norm = math.sqrt(sum(x * x for x in out[0]))
    assert abs(norm - 1.0) < 1e-9


def test_fake_embedder_deterministic():
    e = FakeEmbedder()
    assert e.embed(["abc"]) == e.embed(["abc"])


def test_fake_embedder_similar_keyword_cosine():
    e = FakeEmbedder()
    doc_restaurant = e.embed(["成都 火锅 麻辣"])[0]
    doc_attraction = e.embed(["宽窄巷子 老街"])[0]
    query = e.embed_query("火锅")
    sim_restaurant = sum(a * b for a, b in zip(doc_restaurant, query))
    sim_attraction = sum(a * b for a, b in zip(doc_attraction, query))
    assert sim_restaurant > sim_attraction


def test_embedder_interface_shape():
    """真实 Embedder 的构造签名存在（不加载模型）。"""
    from app.rag.embeddings import Embedder, MODEL_ID

    assert Embedder.__init__.__code__.co_argcount == 2  # (self, model_path)
    assert MODEL_ID == "BAAI/bge-small-zh-v1.5"
    assert hasattr(Embedder, "embed_query")
```
预期：FAIL —— `ModuleNotFoundError: No module named 'app.rag'`。

- [ ] **Step 2: 实现 Embedding 层**

`backend/app/rag/embeddings.py`：
```python
"""BGE 中文 embedding 封装。

- 模型：BAAI/bge-small-zh-v1.5（512 维，约 95MB，CPU 推理）
- 下载：ModelScope（huggingface.co 在中国大陆不可达），见 download_model.py
- 池化：BGE 官方要求 [CLS] token 池化 + L2 归一化
- 检索指令：query 侧必须加前缀"为这个句子生成表示以用于检索相关文章："，
  document 侧不加 —— 这是 bge 检索质量的关键细节

测试不加载真实模型（FakeEmbedder 替代）；真实加载只在
python -m app.rag.download_model + ingest 冒烟时发生。
"""
from __future__ import annotations

from transformers import AutoModel, AutoTokenizer

MODEL_ID = "BAAI/bge-small-zh-v1.5"

# BGE 官方查询指令（仅 query 侧使用）
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class Embedder:
    def __init__(self, model_path: str) -> None:
        """model_path 为 ModelScope 下载后的本地目录。"""
        self._tokenizer = AutoTokenizer.from_pretrained(model_path)
        self._model = AutoModel.from_pretrained(model_path)
        self._model.eval()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """文档侧编码（不加指令），返回 L2 归一化向量列表。"""
        return self._encode(texts, with_instruction=False)

    def embed_query(self, text: str) -> list[float]:
        """查询侧编码（加指令前缀）。"""
        return self._encode([text], with_instruction=True)[0]

    def _encode(self, texts: list[str], *, with_instruction: bool) -> list[list[float]]:
        import torch

        if with_instruction:
            texts = [QUERY_INSTRUCTION + t for t in texts]
        inputs = self._tokenizer(
            texts, padding=True, truncation=True, max_length=512, return_tensors="pt"
        )
        with torch.no_grad():
            outputs = self._model(**inputs)
        # CLS token 池化
        cls_vectors = outputs.last_hidden_state[:, 0, :]
        # L2 归一化
        normed = torch.nn.functional.normalize(cls_vectors, p=2, dim=1)
        return normed.tolist()
```

`backend/app/rag/download_model.py`：
```python
"""下载 BGE 模型（ModelScope）。用法：python -m app.rag.download_model

huggingface.co 在中国大陆不可达，模型必须从 ModelScope 拉取到本地目录，
之后加载走本地路径（离线）。已存在时跳过（可重试）。
"""
import os
import sys
from pathlib import Path

from app.rag.embeddings import MODEL_ID


def default_model_dir() -> Path:
    return Path(os.environ.get("RAG_MODEL_DIR", Path(__file__).resolve().parents[2] / "data" / "bge-model"))


def ensure_model(model_dir: str | Path) -> str:
    """下载（若不存在）并返回本地模型路径。"""
    model_dir = Path(model_dir)
    if model_dir.exists() and any(model_dir.iterdir()):
        return str(model_dir)
    from modelscope import snapshot_download

    model_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(MODEL_ID, local_dir=str(model_dir))
    return str(model_dir)


def main() -> None:
    model_dir = default_model_dir()
    path = ensure_model(model_dir)
    print(f"BGE 模型就绪: {path}")


if __name__ == "__main__":
    sys.exit(main())
```

`backend/pyproject.toml`（dependencies 追加 RAG 依赖）：
```toml
[project]
# ...其余不变...
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "langgraph>=0.2",
    "pydantic>=2.7",
    "httpx>=0.27",
    "chromadb>=1.5",
    "transformers>=4.44",
    "torch>=2.2",
    "sentencepiece>=0.2",
    "modelscope>=1.15",
]
```

- [ ] **Step 3: 运行测试验证通过**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_embeddings.py -v`
预期：4 passed。再跑全量 `pytest -v` → 15 passed。
（若 transformerschromadb 等尚未安装，先 `pip install -e ".[dev]"` 更新依赖——Task 2 起 RAG 依赖进入 pyproject。）

- [ ] **Step 4: 提交**

```bash
cd /d/agent
git add backend/
git commit -m "feat(backend): BGE embedding 层（ModelScope 下载 + CLS 池化 + 查询指令）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Chroma 向量库封装

**Files:**
- Create: `backend/app/rag/vector_store.py`
- Test: `backend/tests/test_vector_store.py`

**Interfaces:**
- Consumes: `FakeEmbedder`（conftest）
- Produces: `VectorStore`（upsert_pois / query / get_all / count）；POI dict 规范字段

- [ ] **Step 1: 写失败测试**

`backend/tests/test_vector_store.py`：
```python
from app.rag.vector_store import VectorStore

from conftest import FakeEmbedder


def _poi(i: int, city: str = "北京", category: str = "attraction", name: str = "景点", tags=None) -> dict:
    return {
        "poi_id": f"test-{i:03d}", "city": city, "name": name,
        "category": category, "rating": 4.5, "price_tier": 2,
        "lat": 39.9, "lng": 116.4, "description": f"第{i}个测试点",
        "tags": tags or ["测试"],
    }


def test_upsert_and_count(tmp_path):
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    assert store.count() == 0
    n = store.upsert_pois([_poi(1), _poi(2)])
    assert n == 2 and store.count() == 2
    # 重复 upsert 幂等（同一 poi_id 覆盖）
    store.upsert_pois([_poi(1)])
    assert store.count() == 2


def test_query_by_city_and_category(tmp_path):
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([
        _poi(1, city="北京", category="attraction", name="故宫博物院"),
        _poi(2, city="北京", category="restaurant", name="全聚德烤鸭"),
        _poi(3, city="成都", category="restaurant", name="蜀大侠火锅"),
    ])
    hits = store.query("故宫", city="北京", category="attraction", k=5)
    assert [p["poi_id"] for p in hits] == ["test-001"]
    hits2 = store.query("火锅", city="成都")
    assert hits2 and hits2[0]["poi_id"] == "test-003"


def test_query_empty_text_sorts_by_rating(tmp_path):
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([
        _poi(1, name="普通景点", rating=4.0),
        _poi(2, name="高分景点", rating=4.9),
    ])
    hits = store.query("", city="北京", category="attraction", k=5)
    assert hits[0]["poi_id"] == "test-002"  # rating 高者在前


def test_get_all_and_poi_shape(tmp_path):
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([_poi(1, tags=["历史", "免费"]), _poi(2, city="成都")])
    all_pois = store.get_all()
    assert len(all_pois) == 2
    first = all_pois[0]
    required = {"poi_id", "city", "name", "category", "rating",
                "price_tier", "lat", "lng", "description", "tags"}
    assert set(first) == required
    assert first["tags"] == ["历史", "免费"]  # tags 恢复为 list
    assert store.get_all(city="成都")[0]["poi_id"] == "test-002"
```
预期：FAIL —— `ModuleNotFoundError: No module named 'app.rag.vector_store'`。

- [ ] **Step 2: 实现向量库**

`backend/app/rag/vector_store.py`：
```python
"""Chroma 向量库封装。

- 存储：PersistentClient（backend/data/chroma，TRAVEL_DB 同款 env 可覆盖）
- 集合：poi_kb，cosine 空间，自定义 embedding_function（注入 Embedder/FakeEmbedder）
- 文档文本：name + description + tags + category + city 聚合（检索语义的来源）
- metadata：{poi_id, city, name, category, rating, price_tier, lat, lng,
  description, tags_str}（tags 以逗号拼接，返回时还原为 list）
"""
from __future__ import annotations

from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb import PersistentClient

COLLECTION_NAME = "poi_kb"


class _BgeEmbeddingFunction(EmbeddingFunction):
    """把外部 embedder 适配为 Chroma 的 EmbeddingFunction 协议。"""

    def __init__(self, embedder) -> None:
        self._embedder = embedder

    def __call__(self, input: Documents) -> Embeddings:
        return self._embedder.embed(list(input))


def _doc_text(p: dict) -> str:
    tags = "、".join(p.get("tags", []))
    return f"{p['name']}。{p.get('description', '')}。标签：{tags}。类别：{p['category']}。城市：{p['city']}"


def _meta(p: dict) -> dict:
    return {
        "poi_id": p["poi_id"], "city": p["city"], "name": p["name"],
        "category": p["category"], "rating": float(p["rating"]),
        "price_tier": int(p["price_tier"]), "lat": float(p["lat"]),
        "lng": float(p["lng"]), "description": p.get("description", ""),
        "tags_str": ",".join(p.get("tags", [])),
    }


def _poi_dict(meta: dict) -> dict:
    d = {k: meta[k] for k in
         ("poi_id", "city", "name", "category", "rating",
          "price_tier", "lat", "lng", "description")}
    d["tags"] = meta["tags_str"].split(",") if meta.get("tags_str") else []
    return d


class VectorStore:
    def __init__(self, persist_dir: str, embedder) -> None:
        self._client = PersistentClient(path=persist_dir)
        self._col = self._client.get_or_create_collection(
            COLLECTION_NAME,
            embedding_function=_BgeEmbeddingFunction(embedder),
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_pois(self, pois: list[dict]) -> int:
        """幂等入库：同一 poi_id 覆盖；返回条数。"""
        if not pois:
            return 0
        self._col.upsert(
            ids=[p["poi_id"] for p in pois],
            documents=[_doc_text(p) for p in pois],
            metadatas=[_meta(p) for p in pois],
        )
        return len(pois)

    def query(
        self,
        text: str,
        *,
        city: str | None = None,
        category: str | None = None,
        k: int = 10,
    ) -> list[dict]:
        """向量检索；text 为空时退化为 metadata 过滤 + rating 降序。"""
        where = self._where(city, category)
        if text.strip():
            result = self._col.query(query_texts=[text], where=where, n_results=k)
        else:
            fetched = self._col.get(where=where, limit=1000)
            metas = fetched.get("metadatas") or []
            metas = sorted(metas, key=lambda m: m.get("rating", 0), reverse=True)
            return [_poi_dict(m) for m in metas[:k]]
        return [_poi_dict(m) for m in (result.get("metadatas") or [[]])[0]]

    def get_all(self, city: str | None = None, category: str | None = None) -> list[dict]:
        fetched = self._col.get(where=self._where(city, category), limit=1000)
        return [_poi_dict(m) for m in (fetched.get("metadatas") or [])]

    def count(self) -> int:
        return self._col.count()

    @staticmethod
    def _where(city: str | None, category: str | None) -> dict | None:
        if city and category:
            return {"$and": [{"city": city}, {"category": category}]}
        if city:
            return {"city": city}
        if category:
            return {"category": category}
        return None
```

- [ ] **Step 3: 运行测试验证通过**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_vector_store.py -v`
预期：4 passed。

- [ ] **Step 4: 提交**

```bash
cd /d/agent
git add backend/
git commit -m "feat(backend): Chroma 向量库封装（自定义 embedding_function + 幂等入库）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: POI 语料生成 + 入库（ingest）

**Files:**
- Create: `backend/app/rag/generate.py`
- Create: `backend/app/rag/ingest.py`
- Create: `backend/data/.gitkeep`（并修改 `.gitignore` 追加 `backend/data/`）
- Test: `backend/tests/test_generate.py`、`backend/tests/test_ingest.py`

**Interfaces:**
- Consumes: `DeepSeekProvider.chat_json`、`VectorStore.upsert_pois`、`FakeEmbedder`
- Produces: `CITIES`/`CITY_EN`/`CITY_COORDS`（20 城）、`generate_city`、`validate_pois`、`load_corpus`、`run_ingest`

**注意：** 测试全部用 FakeProvider / FakeEmbedder / tmp_path；**真实生成与入库是手动冒烟步骤**（需要 DEEPSEEK_API_KEY + 已下载模型）。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_generate.py`：
```python
import pytest

from app.llm.deepseek import DeepSeekProvider
from app.rag import generate

from conftest import FakeProvider

CITY_RESPONSE = {
    "city": "成都",
    "pois": [
        {"name": "宽窄巷子", "category": "attraction", "lat": 30.67, "lng": 104.06,
         "rating": 4.6, "price_tier": 1, "description": "老成都街区，小吃与茶馆集中。",
         "tags": ["老街", "小吃"]},
        {"name": "蜀大侠火锅", "category": "restaurant", "lat": 30.66, "lng": 104.07,
         "rating": 4.5, "price_tier": 3, "description": "本地连锁火锅，麻辣鲜香。",
         "tags": ["火锅", "麻辣"]},
    ],
}


def _fake() -> FakeProvider:
    return FakeProvider(json_responses={"成都": CITY_RESPONSE})


def test_cities_cover_20():
    assert len(generate.CITIES) == 20
    assert "北京" in generate.CITIES and "成都" in generate.CITIES


def test_generate_city_parses():
    fake = _fake()
    pois = generate.generate_city(fake, "成都")  # type: ignore[arg-type]
    assert len(pois) == 2
    assert pois[0]["name"] == "宽窄巷子"
    assert pois[0]["city"] == "成都"
    assert fake.calls[0][0]["role"] == "system"


def test_validate_drops_bad_entries():
    good = {"name": "故宫", "category": "attraction", "lat": 39.9, "lng": 116.4,
            "rating": 4.8, "price_tier": 2, "description": "紫禁城。", "tags": ["历史"]}
    bad_coord = dict(good, name="坐标越界", lat=80.0, lng=200.0)
    bad_cat = dict(good, name="类别非法", category="spa")
    bad_rating = dict(good, name="评分非法", rating=9.9)
    out = generate.validate_pois("北京", [good, bad_coord, bad_cat, bad_rating])
    assert len(out) == 1 and out[0]["name"] == "故宫"
```

`backend/tests/test_ingest.py`：
```python
from app.rag.ingest import load_corpus, run_ingest
from app.rag.vector_store import VectorStore

from conftest import FakeEmbedder

CORPUS_LINES = [
    '{"name": "宽窄巷子", "city": "成都", "category": "attraction", "lat": 30.67, "lng": 104.06, "rating": 4.6, "price_tier": 1, "description": "老成都街区。", "tags": ["老街"]}',
    '{"name": "蜀大侠火锅", "city": "成都", "category": "restaurant", "lat": 30.66, "lng": 104.07, "rating": 4.5, "price_tier": 3, "description": "麻辣火锅。", "tags": ["火锅"]}',
    '{"name": "非法条目", "city": "成都", "category": "spa", "lat": 30.6, "lng": 104.0, "rating": 4.0, "price_tier": 1, "description": "x", "tags": []}',
]


def test_load_corpus_generates_poi_ids(tmp_path):
    p = tmp_path / "corpus.jsonl"
    p.write_text("\n".join(CORPUS_LINES), encoding="utf-8")
    pois = load_corpus(str(p))
    assert len(pois) == 2  # 非法类别被校验丢弃
    assert pois[0]["poi_id"] == "chengdu-001"
    assert pois[1]["poi_id"] == "chengdu-002"


def test_run_ingest_upserts(tmp_path):
    p = tmp_path / "corpus.jsonl"
    p.write_text("\n".join(CORPUS_LINES), encoding="utf-8")
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    n = run_ingest(str(p), store)
    assert n == 2
    assert store.count() == 2
```

- [ ] **Step 2: 实现生成与入库**

`backend/app/rag/generate.py`：
```python
"""POI 语料生成：DeepSeek 按城市模板批量生成（一次一城，JSON 模式）。

产物是 backend/data/poi_corpus.jsonl，数据为 **AI 生成示例数据，
坐标仅供参考**（README 与前端展示均注明）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from app.llm.deepseek import DeepSeekProvider

CITIES = [
    "北京", "上海", "成都", "西安", "杭州", "广州", "深圳", "南京", "苏州",
    "重庆", "厦门", "青岛", "大连", "长沙", "武汉", "昆明", "大理", "丽江",
    "三亚", "洛阳",
]

CITY_EN = {
    "北京": "beijing", "上海": "shanghai", "成都": "chengdu", "西安": "xian",
    "杭州": "hangzhou", "广州": "guangzhou", "深圳": "shenzhen", "南京": "nanjing",
    "苏州": "suzhou", "重庆": "chongqing", "厦门": "xiamen", "青岛": "qingdao",
    "大连": "dalian", "长沙": "changsha", "武汉": "wuhan", "昆明": "kunming",
    "大理": "dali", "丽江": "lijiang", "三亚": "sanya", "洛阳": "luoyang",
}

# 城市中心坐标（用于生成时约束坐标范围与 ingest 校验）
CITY_COORDS: dict[str, tuple[float, float]] = {
    "北京": (39.9042, 116.4074), "上海": (31.2304, 121.4737), "成都": (30.5728, 104.0668),
    "西安": (34.3416, 108.9398), "杭州": (30.2741, 120.1551), "广州": (23.1291, 113.2644),
    "深圳": (22.5431, 114.0579), "南京": (32.0603, 118.7969), "苏州": (31.2989, 120.5853),
    "重庆": (29.5630, 106.5516), "厦门": (24.4798, 118.0894), "青岛": (36.0671, 120.3826),
    "大连": (38.9140, 121.6147), "长沙": (28.2282, 112.9388), "武汉": (30.5928, 114.3055),
    "昆明": (24.8801, 102.8329), "大理": (25.6065, 100.2676), "丽江": (26.8721, 100.2299),
    "三亚": (18.2528, 109.5119), "洛阳": (34.6197, 112.4540),
}

VALID_CATEGORIES = {"attraction", "restaurant", "hotel"}
VALID_TIERS = {1, 2, 3, 4}

GENERATE_SYSTEM_PROMPT = """你是中国旅游 POI 数据生成器。为指定城市生成景点/酒店/餐厅条目（AI 生成示例数据，坐标仅供参考，但要落在该城市市中心周边合理范围）。
只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{"city": "城市名", "pois": [
  {"name": "中文名", "category": "attraction|restaurant|hotel",
   "lat": 纬度, "lng": 经度, "rating": 3.5到5.0一位小数,
   "price_tier": 1到4整数, "description": "50字以内，真实、信息密度高",
   "tags": ["2-4个标签，如 历史/夜景/亲子/排队/免费"]}
]}
数量要求：景点 8-10 个、餐厅 5-6 家（含本地特色美食）、酒店 3-4 家（覆盖经济/舒适/高档价位）。"""


def generate_city(provider: DeepSeekProvider, city: str) -> list[dict]:
    """调用一次 DeepSeek 生成一城 POI，返回校验后的条目（含 city 字段）。"""
    lat, lng = CITY_COORDS[city]
    messages = [
        {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"请为「{city}」生成 POI 数据。市中心坐标约 ({lat}, {lng})，"
            "所有条目坐标必须在市中心 ±2 度范围内。只输出 JSON。"
        )},
    ]
    raw = provider.chat_json(messages)
    pois = raw.get("pois", []) if isinstance(raw, dict) else []
    return validate_pois(city, pois)


def validate_pois(city: str, pois: list[dict]) -> list[dict]:
    """字段/类别/评分/价位/坐标校验；非法条目丢弃。"""
    clat, clng = CITY_COORDS[city]
    out = []
    for p in pois:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name", "")).strip()
        category = p.get("category")
        if not name or category not in VALID_CATEGORIES:
            continue
        try:
            lat, lng = float(p["lat"]), float(p["lng"])
            rating = float(p["rating"])
            tier = int(p["price_tier"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (3.5 <= rating <= 5.0 and tier in VALID_TIERS):
            continue
        if abs(lat - clat) > 2.0 or abs(lng - clng) > 2.0:
            continue  # 坐标越界丢弃
        desc = str(p.get("description", "")).strip()
        if not desc:
            continue
        tags = [str(t) for t in p.get("tags", []) if str(t).strip()][:4]
        out.append({
            "poi_id": "", "city": city, "name": name, "category": category,
            "lat": lat, "lng": lng, "rating": rating, "price_tier": tier,
            "description": desc, "tags": tags,
        })
    return out


def default_corpus_path() -> Path:
    return Path(os.environ.get("POI_CORPUS_PATH", Path(__file__).resolve().parents[2] / "data" / "poi_corpus.jsonl"))


def main() -> int:
    provider = DeepSeekProvider(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
    )
    out_path = default_corpus_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with out_path.open("w", encoding="utf-8") as f:
        for city in CITIES:
            pois = generate_city(provider, city)
            for p in pois:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
            total += len(pois)
            print(f"{city}: {len(pois)} 条")
    print(f"完成：{total} 条 → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`backend/app/rag/ingest.py`：
```python
"""POI 语料入库：读取 JSONL → 校验 → 生成 poi_id → 向量化 → Chroma upsert。

用法：python -m app.rag.ingest
（前置：python -m app.rag.download_model 下载 BGE 模型）
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from app.rag.embeddings import Embedder
from app.rag.generate import CITY_EN, default_corpus_path
from app.rag.vector_store import VectorStore

VALID_CATEGORIES = {"attraction", "restaurant", "hotel"}


def load_corpus(jsonl_path: str | Path) -> list[dict]:
    """读取语料 JSONL：校验 + 生成 poi_id（{城市拼音}-{序号:03d}）。"""
    pois: list[dict] = []
    with Path(jsonl_path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                p = json.loads(line)
            except json.JSONDecodeError:
                continue
            city = p.get("city")
            if not city or city not in CITY_EN or p.get("category") not in VALID_CATEGORIES:
                continue
            p["city"] = city
            pois.append(p)
    counts: dict[str, int] = {}
    for p in pois:
        key = p["city"]
        counts[key] = counts.get(key, 0) + 1
        p["poi_id"] = f"{CITY_EN[key]}-{counts[key]:03d}"
    return pois


def run_ingest(jsonl_path: str | Path, store: VectorStore) -> int:
    """读取 + 入库，返回入库条数。"""
    pois = load_corpus(jsonl_path)
    return store.upsert_pois(pois)


def default_chroma_dir() -> Path:
    return Path(os.environ.get("CHROMA_PERSIST_DIR", Path(__file__).resolve().parents[2] / "data" / "chroma"))


def main() -> int:
    from app.rag.download_model import ensure_model, default_model_dir

    model_path = ensure_model(default_model_dir())
    print(f"加载 BGE: {model_path}")
    embedder = Embedder(model_path)
    store = VectorStore(str(default_chroma_dir()), embedder)
    corpus = default_corpus_path()
    n = run_ingest(str(corpus), store)
    print(f"入库完成：{n} 条，库内总数 {store.count()} → {default_chroma_dir()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 运行测试验证通过 + .gitignore**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_generate.py tests/test_ingest.py -v`
预期：3 passed。

修改 `.gitignore`（追加）：
```
# 运行时数据：RAG 向量库 / POI 语料 / 模型缓存
backend/data/
```

- [ ] **Step 4: 提交**

```bash
cd /d/agent
git add backend/ .gitignore
git commit -m "feat(backend): POI 语料生成与入库（DeepSeek 批量 + 校验 + Chroma ingest）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 5: 手动冒烟（真实模型 + 真实语料，一次性）**

```bash
cd /d/agent/backend
# 1. 下载 BGE 模型（ModelScope，约 95MB）
.venv/Scripts/python -m app.rag.download_model
# 2. 生成 20 城语料（需要 DEEPSEEK_API_KEY，约 20 次调用）
DEEPSEEK_API_KEY=sk-xxx .venv/Scripts/python -m app.rag.generate
# 3. 向量化入库（真实 BGE，几分钟）
.venv/Scripts/python -m app.rag.ingest
```
预期：`入库完成：≥300 条`；手工抽查 `backend/data/poi_corpus.jsonl`（每城 15-25 条、坐标在市中心周边）。
（若某城生成失败可单独重跑：临时改 CITIES 只含该城后再次执行。）

---

### Task 5: 检索器（retriever）

**Files:**
- Create: `backend/app/rag/retriever.py`
- Create: `backend/tests/fixtures/sample_pois.jsonl`
- Test: `backend/tests/test_retriever.py`

**Interfaces:**
- Consumes: `VectorStore`、`CITIES`/`CITY_EN`/`CITY_COORDS`（generate.py）
- Produces: `normalize_city` / `search_pois` / `get_poi` / `search_nearby` / `get_store` / `set_store`

- [ ] **Step 1: 写失败测试**

`backend/tests/fixtures/sample_pois.jsonl`：
```json
{"name": "故宫博物院", "city": "北京", "category": "attraction", "lat": 39.9163, "lng": 116.3972, "rating": 4.8, "price_tier": 2, "description": "明清两代皇宫，世界最大木结构建筑群，需提前预约。", "tags": ["历史", "预约"]}
{"name": "全聚德烤鸭（前门店）", "city": "北京", "category": "restaurant", "lat": 39.8997, "lng": 116.3967, "rating": 4.4, "price_tier": 4, "description": "挂炉烤鸭百年老店，鸭皮酥脆。", "tags": ["烤鸭", "老字号"]}
{"name": "四季民福烤鸭店（故宫店）", "city": "北京", "category": "restaurant", "lat": 39.9180, "lng": 116.4000, "rating": 4.6, "price_tier": 3, "description": "烤鸭性价比之选，靠窗可望故宫角楼。", "tags": ["烤鸭", "景观位"]}
{"name": "北京王府井文华东方酒店", "city": "北京", "category": "hotel", "lat": 39.9150, "lng": 116.4110, "rating": 4.8, "price_tier": 4, "description": "紫禁城景观豪华酒店。", "tags": ["豪华", "景观"]}
{"name": "宽窄巷子", "city": "成都", "category": "attraction", "lat": 30.67, "lng": 104.06, "rating": 4.6, "price_tier": 1, "description": "老成都街区，小吃与茶馆集中。", "tags": ["老街", "小吃"]}
{"name": "蜀大侠火锅（春熙路店）", "city": "成都", "category": "restaurant", "lat": 30.66, "lng": 104.07, "rating": 4.5, "price_tier": 3, "description": "本地连锁火锅，麻辣鲜香。", "tags": ["火锅", "麻辣"]}
{"name": "成都群光君悦酒店", "city": "成都", "category": "hotel", "lat": 30.66, "lng": 104.08, "rating": 4.7, "price_tier": 4, "description": "春熙路商圈豪华酒店。", "tags": ["商圈", "豪华"]}
```

`backend/tests/test_retriever.py`：
```python
import math
from pathlib import Path

import pytest

from app.rag import retriever
from app.rag.ingest import load_corpus
from app.rag.vector_store import VectorStore

from conftest import FakeEmbedder

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pois.jsonl"


@pytest.fixture()
def store(tmp_path):
    s = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    s.upsert_pois(load_corpus(FIXTURE))
    retriever.set_store(s)
    yield s
    retriever.set_store(None)


def test_normalize_city_aliases():
    assert retriever.normalize_city("北京") == "北京"
    assert retriever.normalize_city("beijing") == "北京"
    assert retriever.normalize_city("BeiJing") == "北京"
    assert retriever.normalize_city("成都") == "成都"
    assert retriever.normalize_city("chengdu") == "成都"
    assert retriever.normalize_city("巴黎") is None


def test_search_pois_by_category(store):
    pois = retriever.search_pois("北京", category="restaurant")
    assert {p["name"] for p in pois} == {"全聚德烤鸭（前门店）", "四季民福烤鸭店（故宫店）"}


def test_search_pois_semantic_query(store):
    pois = retriever.search_pois("成都", query="火锅")
    assert pois and pois[0]["name"].startswith("蜀大侠火锅")


def test_search_pois_unknown_city(store):
    assert retriever.search_pois("巴黎") == []


def test_get_poi(store):
    p = retriever.get_poi("beijing-001")
    assert p and p["name"] == "故宫博物院"
    assert retriever.get_poi("nope") is None


def test_search_nearby_radius_and_sort(store):
    # 故宫(39.9163, 116.3972) 周边 3km：四季民福(39.9180, 116.4000) 近，全聚德(39.8997, 116.3967) 远
    nearby = retriever.search_nearby(39.9163, 116.3972, category="restaurant", radius_km=3.0, k=5)
    assert nearby[0]["name"] == "四季民福烤鸭店（故宫店）"
    dist = retriever._haversine(39.9163, 116.3972, 39.9180, 116.4000)
    assert 0 < dist < 3.0


def test_get_store_without_set_raises(monkeypatch, tmp_path):
    # 模型目录与 chroma 目录都指到不存在的位置：get_store 必须在加载模型
    # 之前快速失败（模型不存在 → RuntimeError），而不是尝试联网下载挂起
    monkeypatch.setenv("RAG_MODEL_DIR", str(tmp_path / "no-model"))
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "no-chroma"))
    with pytest.raises(RuntimeError, match="模型未就绪"):
        retriever.get_store()
```
预期：FAIL —— `ModuleNotFoundError: No module named 'app.rag.retriever'`。

（注意 `test_get_store_without_set_raises`：get_store 在模型未下载时抛 RuntimeError 并提示先运行 `python -m app.rag.download_model`——**不在服务进程内触发联网下载**（避免挂起），下载是显式 CLI 步骤。）

- [ ] **Step 2: 实现检索器**

`backend/app/rag/retriever.py`：
```python
"""RAG 检索对外接口（Planner 依赖注入点）。

- search_pois：同城 + 类别过滤 + 语义检索（query 为空按 rating 降序）
- search_nearby："周边"检索 —— 同城 + haversine 距离排序（radius_km 内）
- get_store：惰性单例（CHROMA_PERSIST_DIR + 真实 BGE）；set_store 供测试注入
"""
from __future__ import annotations

import math

from app.rag.generate import CITY_EN
from app.rag.vector_store import VectorStore

# 城市别名（中文名 + 拼音，大小写不敏感）
_CITY_ALIASES: dict[str, str] = {c: c for c in CITY_EN}
_CITY_ALIASES.update({en: c for c, en in CITY_EN.items()})

_store: VectorStore | None = None


def set_store(store: VectorStore | None) -> None:
    """测试注入点：替换全局检索存储（FakeEmbedder 版）。"""
    global _store
    _store = store


def get_store() -> VectorStore:
    """惰性单例；首次调用创建（CHROMA_PERSIST_DIR + 真实 BGE）。

    模型未下载时抛 RuntimeError 提示先执行 `python -m app.rag.download_model`——
    不在服务进程内触发联网下载（避免请求挂起），下载是显式 CLI 步骤。
    """
    global _store
    if _store is None:
        from app.rag.download_model import default_model_dir
        from app.rag.embeddings import Embedder
        from app.rag.ingest import default_chroma_dir

        model_path = default_model_dir()
        if not (model_path.exists() and any(model_path.iterdir())):
            raise RuntimeError(
                f"BGE 模型未就绪：{model_path}。请先运行 python -m app.rag.download_model"
            )
        embedder = Embedder(str(model_path))
        _store = VectorStore(str(default_chroma_dir()), embedder)
    return _store


def normalize_city(name: str) -> str | None:
    """中文名/拼音归一为 CITY_EN 的城市名，无法识别返回 None。"""
    return _CITY_ALIASES.get(name.strip().lower())


def search_pois(
    city: str,
    *,
    category: str | None = None,
    query: str | None = None,
    k: int = 10,
) -> list[dict]:
    """同城检索；query 提供时语义排序，否则按 rating 降序。"""
    city = normalize_city(city)
    if city is None:
        return []
    return get_store().query(query or "", city=city, category=category, k=k)


def get_poi(poi_id: str) -> dict | None:
    """按 poi_id 取 POI；不存在返回 None。"""
    for p in get_store().get_all():
        if p["poi_id"] == poi_id:
            return p
    return None


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点球面距离（km）。"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def search_nearby(
    lat: float,
    lng: float,
    *,
    category: str | None = None,
    radius_km: float = 3.0,
    k: int = 5,
) -> list[dict]:
    """同城候选 + 距离过滤排序的"周边"检索（数据量小，全量计算即可）。"""
    candidates = [p for p in get_store().get_all(category=category) if p.get("lat") is not None]
    scored = []
    for p in candidates:
        d = _haversine(lat, lng, float(p["lat"]), float(p["lng"]))
        if d <= radius_km:
            scored.append((d, p))
    scored.sort(key=lambda item: item[0])
    return [p for _, p in scored[:k]]
```

- [ ] **Step 3: 运行测试验证通过**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_retriever.py -v`
预期：7 passed。再跑全量 `pytest -v` → 全部 PASS。

- [ ] **Step 4: 提交**

```bash
cd /d/agent
git add backend/
git commit -m "feat(backend): RAG 检索器（同城语义检索 + 周边距离排序）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 天气适配器（Open-Meteo + 模拟降级）

**Files:**
- Create: `backend/app/tools/__init__.py`（空）
- Create: `backend/app/tools/weather_api.py`
- Test: `backend/tests/test_weather_api.py`

**Interfaces:**
- Produces: `get_weather(lat, lng, *, days=5, client=None) -> list[dict]`、`WEATHERCODES`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_weather_api.py`：
```python
import httpx
from httpx import MockTransport

from app.tools import weather_api


def _make_client(days: int, lat: float, lng: float) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert f"latitude={lat}" in url and f"longitude={lng}" in url
        assert f"forecast_days={days}" in url
        return httpx.Response(
            200,
            json={
                "daily": {
                    "time": ["2026-10-01", "2026-10-02"],
                    "temperature_2m_max": [24.0, 21.0],
                    "temperature_2m_min": [16.0, 14.0],
                    "weathercode": [1, 61],
                }
            },
        )

    return httpx.Client(transport=MockTransport(handler))


def test_get_weather_success():
    fake = _make_client(2, 35.6, 139.6)
    out = weather_api.get_weather(35.6, 139.6, days=2, client=fake)
    assert out == [
        {"date": "2026-10-01", "t_max": 24.0, "t_min": 16.0, "condition": "多云", "source": "open-meteo"},
        {"date": "2026-10-02", "t_max": 21.0, "t_min": 14.0, "condition": "雨", "source": "open-meteo"},
    ]


def test_get_weather_falls_back_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    fake = httpx.Client(transport=MockTransport(handler))
    out = weather_api.get_weather(35.6, 139.6, days=2, client=fake)
    assert len(out) == 2
    assert all(d["source"] == "simulated" for d in out)
    assert out[0]["date"] == "2026-10-01"


def test_get_weather_falls_back_on_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    fake = httpx.Client(transport=MockTransport(handler))
    out = weather_api.get_weather(35.6, 139.6, days=2, client=fake)
    assert all(d["source"] == "simulated" for d in out)


def test_weathercodes_cover_simulated_default():
    assert weather_api.WEATHERCODES[0] == "晴"
```
预期：FAIL —— `ModuleNotFoundError`。

- [ ] **Step 2: 实现天气适配器**

`backend/app/tools/weather_api.py`：
```python
"""天气适配器：Open-Meteo（免 key）真实 API + 失败降级为模拟数据。

成功数据 source="open-meteo"，降级数据 source="simulated"（确定性生成），
调用方（Planner）无需区分即可使用。
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any

import httpx

BASE_URL = "https://api.open-meteo.com/v1/forecast"

# https://open-meteo.com/en/docs 的 WMO weather code → 中文
WEATHERCODES: dict[int, str] = {
    0: "晴", 1: "多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    56: "冻雨", 57: "冻雨",
    61: "雨", 63: "雨", 65: "雨",
    66: "冻雨", 67: "冻雨",
    71: "雪", 73: "雪", 75: "雪", 77: "雪",
    80: "阵雨", 81: "阵雨", 82: "阵雨",
    85: "阵雪", 86: "阵雪",
    95: "雷暴", 96: "雷暴", 99: "雷暴",
}


def _condition_cn(code: int) -> str:
    return WEATHERCODES.get(code, "未知")


def _simulated_weather(lat: float, lng: float, days: int) -> list[dict]:
    """确定性模拟：让 Planner 的测试与演示离线可用。"""
    today = dt.date.today()
    seed = int((lat * 10 + lng * 7 + time.time() // 86400) % 3)
    conditions = ["晴", "多云", "雨"]
    out = []
    for i in range(days):
        d = today + dt.timedelta(days=i)
        out.append({
            "date": d.isoformat(),
            "t_max": round(24 + seed + (i % 3) * 2, 1),
            "t_min": round(15 + seed - (i % 2), 1),
            "condition": conditions[(seed + i) % len(conditions)],
            "source": "simulated",
        })
    return out


def get_weather(
    lat: float,
    lng: float,
    *,
    days: int = 5,
    client: httpx.Client | None = None,
) -> list[dict]:
    """查询未来 days 天逐日天气；任何失败都降级为模拟数据（不抛出）。"""
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=10)
    try:
        resp = client.get(
            BASE_URL,
            params={
                "latitude": lat,
                "longitude": lng,
                "daily": "temperature_2m_max,temperature_2m_min,weathercode",
                "timezone": "auto",
                "forecast_days": days,
            },
        )
        resp.raise_for_status()
        daily: dict[str, Any] = resp.json()["daily"]
        times = daily["time"]
        t_max = daily["temperature_2m_max"]
        t_min = daily["temperature_2m_min"]
        codes = daily["weathercode"]
        return [
            {
                "date": times[i],
                "t_max": t_max[i],
                "t_min": t_min[i],
                "condition": _condition_cn(codes[i]),
                "source": "open-meteo",
            }
            for i in range(min(days, len(times)))
        ]
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return _simulated_weather(lat, lng, days)
    finally:
        if own_client:
            client.close()
```

- [ ] **Step 3: 运行测试验证通过**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_weather_api.py -v`
预期：4 passed。

- [ ] **Step 4: 提交**

```bash
cd /d/agent
git add backend/
git commit -m "feat(backend): 天气适配器（Open-Meteo 真实 API + 模拟降级）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Analyst 需求分析师节点

**Files:**
- Create: `backend/app/agents/__init__.py`（空）
- Create: `backend/app/agents/analyst.py`
- Test: `backend/tests/test_analyst.py`

**Interfaces:**
- Consumes: `DeepSeekProvider.chat_json`、`FakeProvider`（conftest）
- Produces: `analyst_node(state, llm) -> dict`；`build_question(missing) -> str`；`ANALYST_SYSTEM_PROMPT`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_analyst.py`：
```python
from app.agents import analyst

from conftest import FakeProvider


def _state(messages: list[dict]) -> dict:
    return {"messages": messages, "phase": ""}


def _fake() -> FakeProvider:
    return FakeProvider(
        json_responses={
            "成都": {
                "destination": "成都", "duration_days": 3,
                "start_date": None, "budget_cny": 8000,
                "travelers": 2, "preferences": ["美食"],
                "missing": [],
            }
        }
    )


def test_analyst_complete_request_routes_to_planning():
    fake = _fake()
    out = analyst.analyst_node(_state([{"role": "user", "content": "10月去成都玩3天，预算8000，喜欢美食"}]),
                               fake)  # type: ignore[arg-type]
    assert out["phase"] == "planning"
    assert out["profile"]["destination"] == "成都"
    assert out["profile"]["duration_days"] == 3
    assert out["profile"]["budget_cny"] == 8000
    assert out["profile"]["preferences"] == ["美食"]
    assert "messages" not in out  # 无需追问，不追加对话


def test_analyst_missing_destination_asks_question():
    # FakeProvider 按 prompt 子串匹配：key 必须命中 analyst 组装后的 user 内容
    # （"已有画像：…\n最新需求：帮我规划3天行程\n…" → 用 "规划"）
    fake = FakeProvider(
        json_responses={
            "规划": {
                "destination": None, "duration_days": 3, "start_date": None,
                "budget_cny": None, "travelers": 1, "preferences": [],
                "missing": ["destination"],
            }
        }
    )
    out = analyst.analyst_node(_state([{"role": "user", "content": "帮我规划3天行程"}]),
                               fake)  # type: ignore[arg-type]
    assert out["phase"] == "asking"
    question = out["messages"][-1]["content"]
    assert out["messages"][-1]["role"] == "assistant"
    assert "想去哪个城市" in question


def test_analyst_missing_duration_asks_question():
    fake = FakeProvider(
        json_responses={
            "上海": {
                "destination": "上海", "duration_days": None, "start_date": None,
                "budget_cny": None, "travelers": 1, "preferences": [],
                "missing": ["duration_days"],
            }
        }
    )
    out = analyst.analyst_node(_state([{"role": "user", "content": "想去上海玩"}]),
                               fake)  # type: ignore[arg-type]
    assert out["phase"] == "asking"
    assert "几天" in out["messages"][-1]["content"]


def test_analyst_second_turn_merges_profile():
    fake = _fake()
    prior_profile = {"destination": "成都", "duration_days": 3, "budget_cny": 5000}
    state = _state([{"role": "user", "content": "10月去成都玩3天预算8000"}])
    state["profile"] = prior_profile
    out = analyst.analyst_node(state, fake)  # type: ignore[arg-type]
    assert out["profile"]["destination"] == "成都"
    assert out["profile"]["budget_cny"] == 8000  # 新信息覆盖旧值
    assert out["profile"]["travelers"] == 2
```
预期：FAIL —— `ModuleNotFoundError: No module named 'app.agents'`。

- [ ] **Step 2: 实现 Analyst 节点**

`backend/app/agents/analyst.py`：
```python
"""Analyst 需求分析师：抽取出行需求、追问缺失项、构建用户画像。"""
from __future__ import annotations

import json
from typing import Any

from app.llm.deepseek import DeepSeekProvider

ANALYST_SYSTEM_PROMPT = """你是智能旅行助手的"需求分析师"。你的任务是从用户的出行需求中抽取结构化信息。
只输出 JSON 对象（不要任何其他文字、不要 markdown），字段如下：
{
  "destination": "目的地城市（中文名，如 北京/上海/成都/西安；未知为 null）",
  "duration_days": 出行天数（整数，未知为 null）,
  "start_date": "出发日期（YYYY-MM-DD，未知为 null）",
  "budget_cny": 总预算（人民币元，整数，未知为 null）,
  "travelers": 出行人数（整数，未知为 null）,
  "preferences": ["偏好标签，如 美食/购物/文化/自然/亲子"],
  "missing": ["destination", "duration_days", "start_date", "budget_cny", "travelers", "preferences" 中当前未知的字段名]
}
"""

CORE_FIELDS = ["destination", "duration_days"]


def _last_user_message(state: dict) -> str:
    for m in reversed(state["messages"]):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


def build_question(missing: list[str]) -> str:
    """根据缺失字段生成一句中文追问。"""
    parts = []
    if "destination" in missing:
        parts.append("想去哪个城市？")
    if "duration_days" in missing:
        parts.append("打算玩几天？")
    if "start_date" in missing:
        parts.append("大概什么时候出发？")
    if "budget_cny" in missing:
        parts.append("预算大概多少？")
    if "travelers" in missing:
        parts.append("几个人一起去？")
    if "preferences" in missing:
        parts.append("有什么特别偏好吗（美食/购物/文化…）？")
    return "为了帮你规划，还需要补充一下：" + " ".join(parts) if parts else "还需要补充一些信息，请告诉我。"


def analyst_node(state: dict, llm: DeepSeekProvider) -> dict:
    """抽取需求 → 缺失核心字段则追问（phase=asking）→ 否则合入画像（phase=planning）。"""
    profile: dict[str, Any] = dict(state.get("profile", {}))
    user_msg = _last_user_message(state)
    history = state.get("messages", [])
    llm_messages = [
        {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
        {"role": "user", "content": f"已有画像：{json.dumps(profile, ensure_ascii=False)}\n最新需求：{user_msg}\n请按 schema 输出 JSON。"},
    ]
    parsed = llm.chat_json(llm_messages)

    for field in ("destination", "duration_days", "start_date", "budget_cny", "travelers", "preferences"):
        if parsed.get(field) is not None:
            profile[field] = parsed[field]

    missing = [f for f in parsed.get("missing", []) if f in CORE_FIELDS]
    if missing:
        return {
            "phase": "asking",
            "messages": [{"role": "assistant", "content": build_question(missing)}],
            "profile": profile,
        }
    return {"phase": "planning", "profile": profile}
```

- [ ] **Step 3: 运行测试验证通过**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_analyst.py -v`
预期：4 passed。

- [ ] **Step 4: 提交**

```bash
cd /d/agent
git add backend/
git commit -m "feat(backend): Analyst 需求分析师节点

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Planner 行程规划师节点（RAG 检索 + 周边餐厅）

**Files:**
- Create: `backend/app/agents/planner.py`
- Test: `backend/tests/test_planner.py`

**Interfaces:**
- Consumes: `search_pois/search_nearby/get_poi/normalize_city`（Task 5 契约）、`get_weather`（Task 6）、`FakeProvider/fake_weather`
- Produces: `planner_node(state, llm, *, weather_fn, search_pois_fn, search_nearby_fn, get_poi_fn, normalize_city_fn) -> dict`；`build_candidate_context(...) -> str`；`format_itinerary(itinerary) -> str`

**职责：** 用画像（目的地/天数/偏好）+ 天气 + RAG 检索的候选（景点 + 周边餐厅 + 酒店）拼上下文，LLM 只产出结构化行程 JSON（items 引用 poi_id），`format_itinerary` 确定性生成中文 markdown。未知城市返回提示（支持约 20 个国内旅游城市）。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_planner.py`：
```python
import json

from app.agents import planner

from conftest import FakeProvider, fake_weather

ITINERARY = {
    "days": [
        {
            "day": 1,
            "title": "熊猫基地与宽窄巷子",
            "weather_note": "晴 24°C",
            "items": [
                {"time": "09:00", "name": "宽窄巷子", "poi_id": "chengdu-001", "note": "早到避开人流"},
                {"time": "12:00", "name": "蜀大侠火锅（春熙路店）", "poi_id": "chengdu-002", "note": "午餐"},
            ],
        }
    ],
    "summary": "首日老成都街区线。",
    "warnings": [],
}


def _fake() -> FakeProvider:
    return FakeProvider(json_responses={"行程": ITINERARY})


def _state() -> dict:
    return {
        "messages": [{"role": "user", "content": "10月去成都玩3天，预算8000，喜欢美食"}],
        "phase": "planning",
        "profile": {
            "destination": "成都", "duration_days": 1, "start_date": "2026-10-01",
            "budget_cny": 8000, "travelers": 2, "preferences": ["美食"],
        },
    }


# 注入的假检索器：行为与 retriever 契约一致，但数据可控
def _fake_search_pois(city, *, category=None, query=None, k=10):
    assert category is not None  # Planner 必须显式传类别
    pool = {
        "attraction": [{"poi_id": "chengdu-001", "city": "成都", "name": "宽窄巷子",
                        "category": "attraction", "rating": 4.6, "price_tier": 1,
                        "lat": 30.67, "lng": 104.06, "description": "老成都街区。", "tags": ["老街"]}],
        "restaurant": [{"poi_id": "chengdu-002", "city": "成都", "name": "蜀大侠火锅（春熙路店）",
                        "category": "restaurant", "rating": 4.5, "price_tier": 3,
                        "lat": 30.66, "lng": 104.07, "description": "麻辣火锅。", "tags": ["火锅"]}],
        "hotel": [{"poi_id": "chengdu-003", "city": "成都", "name": "成都群光君悦酒店",
                   "category": "hotel", "rating": 4.7, "price_tier": 4,
                   "lat": 30.66, "lng": 104.08, "description": "春熙路商圈豪华酒店。", "tags": ["商圈"]}],
    }
    return pool[category]


def _fake_search_nearby(lat, lng, *, category=None, radius_km=3.0, k=5):
    if category == "restaurant":
        return [{"poi_id": "chengdu-002", "city": "成都", "name": "蜀大侠火锅（春熙路店）",
                 "category": "restaurant", "rating": 4.5, "price_tier": 3,
                 "lat": 30.66, "lng": 104.07, "description": "麻辣火锅。", "tags": ["火锅"]}]
    return []


def _fake_get_poi(poi_id):
    return _fake_search_pois("成都")["attraction"][0] if poi_id == "chengdu-001" else None


def _fake_normalize_city(name):
    return "成都" if "成都" in name else None


def _kwargs():
    return {
        "weather_fn": fake_weather,
        "search_pois_fn": _fake_search_pois,
        "search_nearby_fn": _fake_search_nearby,
        "get_poi_fn": _fake_get_poi,
        "normalize_city_fn": _fake_normalize_city,
    }


def test_planner_produces_reply_and_itinerary():
    fake = _fake()
    out = planner.planner_node(_state(), fake, **_kwargs())  # type: ignore[arg-type]
    assert out["phase"] == "answered"
    assert out["itinerary"]["days"][0]["items"][0]["poi_id"] == "chengdu-001"
    assert out["last_reply"].startswith("## ")


def test_planner_prompt_contains_candidates_and_weather():
    fake = _fake()
    planner.planner_node(_state(), fake, **_kwargs())  # type: ignore[arg-type]
    prompt = fake.calls[0][-1]["content"]
    assert "宽窄巷子" in prompt          # 景点候选进上下文
    assert "蜀大侠火锅" in prompt        # 周边餐厅进上下文
    assert "成都群光君悦酒店" in prompt  # 酒店候选进上下文
    assert "poi_id" in prompt            # 要求引用 POI id
    assert "晴" in prompt                # 天气进上下文


def test_planner_unknown_city_returns_hint():
    fake = _fake()
    state = _state()
    state["profile"]["destination"] = "巴黎"

    def normalize(name):
        return None

    out = planner.planner_node(state, fake, **_kwargs(), normalize_city_fn=normalize)  # type: ignore[arg-type]
    assert out["phase"] == "answered"
    assert "巴黎" in out["last_reply"]
    assert "暂不支持" in out["last_reply"]
    assert fake.calls == []  # 未知城市不调用 LLM


def test_planner_filters_hallucinated_poi():
    fake = FakeProvider(json_responses={"行程": {
        "days": [{"day": 1, "title": "x", "weather_note": "晴",
                  "items": [{"time": "09:00", "name": "编造的店", "poi_id": "nope-999", "note": ""}]}],
        "summary": "x", "warnings": [],
    }})
    out = planner.planner_node(_state(), fake, **_kwargs())  # type: ignore[arg-type]
    assert out["itinerary"]["days"][0]["items"] == []  # 不存在的 poi_id 被清洗


def test_format_itinerary_shape():
    text = planner.format_itinerary(ITINERARY)
    assert "第 1 天" in text and "宽窄巷子" in text
    assert "09:00" in text and "早到避开人流" in text
    assert "## " in text
```

- [ ] **Step 2: 实现 Planner 节点**

`backend/app/agents/planner.py`：
```python
"""Planner 行程规划师：画像 + 天气 + RAG 候选（景点/周边餐厅/酒店）→ 天级行程。

LLM 只产出结构化 JSON（days[] 引用 poi_id），回复文本由 format_itinerary
确定性生成 —— 遵循 spec 风险对策"结构化状态，减少自由文本流转"。
RAG 检索函数通过注入传入（默认 app.rag.retriever），测试注入假实现。
"""
from __future__ import annotations

import json
from collections.abc import Callable

from app.llm.deepseek import DeepSeekProvider
from app.rag.retriever import get_poi as _default_get_poi
from app.rag.retriever import normalize_city as _default_normalize_city
from app.rag.retriever import search_nearby as _default_search_nearby
from app.rag.retriever import search_pois as _default_search_pois
from app.tools.weather_api import get_weather as _default_weather

PLANNER_SYSTEM_PROMPT = """你是智能旅行助手的"行程规划师"。根据用户画像、天气与候选 POI 数据，
生成逐日行程。只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{
  "days": [
    {
      "day": 1,
      "title": "当日主题，如 熊猫基地与宽窄巷子",
      "weather_note": "当日天气一句话，如 晴 24°C",
      "items": [
        {"time": "09:00", "name": "景点名", "poi_id": "候选列表中的 id，必须引用", "note": "为什么去/怎么玩，10-20 字"}
      ]
    }
  ],
  "summary": "整体行程总结，50 字以内",
  "warnings": ["提示，如 需要提前预约/雨天备选，没有则为空数组"]
}
规则：
- 每天 3-5 项，时间从早到晚；餐饮穿插在景点之间，优先选景点"周边餐厅"里的
- 必须从提供的候选 POI 中选取并引用其 poi_id，不要编造
- 雨天（condition 含 雨/雪/雷）优先安排室内景点
- 尊重用户偏好标签（美食/购物/文化/自然/亲子），缺偏好时均衡安排
- 天数以 duration_days 为准，不要多排
"""


def build_candidate_context(
    profile: dict,
    search_pois_fn: Callable,
    search_nearby_fn: Callable,
) -> str:
    """RAG 检索候选并拼成 LLM 上下文：景点（附周边餐厅）+ 酒店。"""
    city = profile["destination"]
    prefs = " ".join(profile.get("preferences", []))
    attractions = search_pois_fn(city, category="attraction", query=prefs or None, k=8)
    hotels = search_pois_fn(city, category="hotel", query=None, k=4)

    lines = ["候选景点（含周边餐厅，周边餐厅可直接选入行程）:"]
    for poi in attractions:
        nearby = search_nearby_fn(
            poi["lat"], poi["lng"], category="restaurant", radius_km=3.0, k=2
        )
        nearby_names = "、".join(r["name"] for r in nearby) or "（无）"
        lines.append(
            f"- {poi['name']}（评分{poi['rating']}，价位档{poi['price_tier']}）: {poi['description']}"
            f" | 周边餐厅: {nearby_names}"
        )
    lines.append("候选酒店:")
    for h in hotels:
        lines.append(
            f"- {h['name']}（评分{h['rating']}，价位档{h['price_tier']}）: {h['description']}"
        )
    return "\n".join(lines)


def format_itinerary(itinerary: dict) -> str:
    """把结构化行程转成中文 markdown 文本（确定性，不依赖 LLM）。"""
    lines: list[str] = []
    for day in itinerary.get("days", []):
        lines.append(f"## 第 {day['day']} 天：{day.get('title', '')}")
        note = day.get("weather_note")
        if note:
            lines.append(f"> 天气：{note}")
        for item in day.get("items", []):
            name = item["name"]
            note_text = item.get("note")
            lines.append(f"- **{item.get('time', '')}** {name}{('（' + note_text + '）') if note_text else ''}")
        lines.append("")
    if itinerary.get("summary"):
        lines.append(f"**行程总结**：{itinerary['summary']}")
    for w in itinerary.get("warnings", []):
        lines.append(f"⚠️ {w}")
    return "\n".join(lines).strip()


def planner_node(
    state: dict,
    llm: DeepSeekProvider,
    *,
    weather_fn: Callable = _default_weather,
    search_pois_fn: Callable = _default_search_pois,
    search_nearby_fn: Callable = _default_search_nearby,
    get_poi_fn: Callable = _default_get_poi,
    normalize_city_fn: Callable = _default_normalize_city,
) -> dict:
    profile: dict = state.get("profile", {})
    destination = profile.get("destination", "")
    city = normalize_city_fn(destination) if destination else None
    if city is None:
        return {
            "phase": "answered",
            "itinerary": {},
            "last_reply": (
                f"目前暂不支持「{destination or '空'}」的行程规划，"
                "当前支持约 20 个国内旅游城市：北京、上海、成都、西安、杭州、"
                "广州、深圳、南京、苏州、重庆、厦门、青岛、大连、长沙、武汉、"
                "昆明、大理、丽江、三亚、洛阳。"
            ),
        }

    from app.rag.generate import CITY_COORDS

    lat, lng = CITY_COORDS[city]
    weather = weather_fn(lat, lng, days=profile.get("duration_days", 3))
    candidate_ctx = build_candidate_context(profile, search_pois_fn, search_nearby_fn)

    llm_messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"画像：{json.dumps(profile, ensure_ascii=False)}\n"
            f"{candidate_ctx}\n"
            f"未来 {len(weather)} 天天气：{json.dumps(weather, ensure_ascii=False)}\n"
            "请按 schema 输出行程 JSON，所有条目必须引用候选 POI 的 poi_id。"
        )},
    ]
    itinerary = llm.chat_json(llm_messages)

    # 清洗：过滤引用不存在的 poi_id 的条目（LLM 幻觉防护）
    for day in itinerary.get("days", []):
        kept = []
        for item in day.get("items", []):
            pid = item.get("poi_id")
            if pid and get_poi_fn(pid) is None:
                continue  # 编造的 POI 直接丢弃
            kept.append(item)
        day["items"] = kept

    source = "open-meteo" if any(w.get("source") == "open-meteo" for w in weather) else "simulated"
    reply = format_itinerary(itinerary)
    if source == "simulated":
        reply += "\n\n_（天气数据暂不可用，已用模拟数据，仅供参考）_"
    return {"phase": "answered", "itinerary": itinerary, "last_reply": reply}
```

- [ ] **Step 3: 运行测试验证通过**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_planner.py -v`
预期：5 passed。

- [ ] **Step 4: 提交**

```bash
cd /d/agent
git add backend/
git commit -m "feat(backend): Planner 行程规划师节点（RAG 候选 + 幻觉清洗 + 确定性格式化）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: 事件总线 + 图装配 + 聊天 API

**Files:**
- Create: `backend/app/events.py`
- Create: `backend/app/api/chat.py`
- Modify: `backend/app/state.py`（扩展 TravelState）
- Modify: `backend/app/graph.py`（整体重写：analyst → 条件路由 → planner，移除 stub）
- Modify: `backend/app/api/sse.py`（走事件总线）
- Modify: `backend/app/main.py`（lifespan + chat 路由）
- Modify: `backend/tests/test_sse.py`（补充 agent_status 用例 + 更新 ping 断言）
- Modify: `backend/tests/test_graph.py`（整体重写）
- Create: `backend/tests/test_events.py`、`backend/tests/test_chat.py`

**Interfaces:**
- Consumes: `analyst_node`、`planner_node`、`DeepSeekProvider`、`FakeProvider/fake_weather` + 假检索器（沿用 Task 8 的注入模式）
- Produces: `events.subscribe/unsubscribe/publish/event_stream`；`build_graph(llm_provider, *, weather_fn, search_pois_fn, search_nearby_fn, get_poi_fn, normalize_city_fn)`；`POST /api/chat`；TravelState 五字段

**注意：** 移除 M1 的模块级 `graph = build_graph()` 单例（改为 main.py lifespan 构建存入 `app.state.graph`）；`test_graph.py` 相应重写；M1 的 `test_sse.py` ping 断言需同步更新（帧格式统一为 `{"type": T, "data": {...}}`）。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_events.py`：
```python
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
```

`backend/tests/test_graph.py`（整体重写）：
```python
from app.graph import build_graph

from conftest import FakeProvider
from test_planner import _kwargs  # 复用 Task 8 的假检索器注入（含 weather_fn）

ITINERARY = {
    "days": [{"day": 1, "title": "熊猫基地", "weather_note": "晴",
              "items": [{"time": "09:00", "name": "宽窄巷子", "poi_id": "chengdu-001", "note": ""}]}],
    "summary": "OK", "warnings": [],
}


def _fake() -> FakeProvider:
    return FakeProvider(
        json_responses={
            "已有画像": {
                "destination": "成都", "duration_days": 1, "start_date": None,
                "budget_cny": 8000, "travelers": 2, "preferences": ["美食"],
                "missing": [],
            },
            "行程": ITINERARY,
        }
    )


def test_full_planning_flow():
    graph = build_graph(_fake(), **_kwargs())  # type: ignore[arg-type]
    result = graph.invoke({
        "messages": [{"role": "user", "content": "10月去成都玩3天，预算8000"}],
        "phase": "",
    })
    assert result["phase"] == "answered"
    assert result["itinerary"]["days"][0]["items"][0]["poi_id"] == "chengdu-001"
    assert result["last_reply"].startswith("## ")


def test_incomplete_request_ends_at_analyst():
    fake = FakeProvider(json_responses={"最新需求": {
        "destination": None, "duration_days": 3, "start_date": None,
        "budget_cny": None, "travelers": 1, "preferences": [],
        "missing": ["destination"],
    }})
    graph = build_graph(fake, **_kwargs())  # type: ignore[arg-type]
    result = graph.invoke({
        "messages": [{"role": "user", "content": "帮我规划3天"}],
        "phase": "",
    })
    assert result["phase"] == "asking"
    assert "想去哪个城市" in result["messages"][-1]["content"]
```
（注：`_kwargs()` 来自 `test_planner.py`，已含全部 5 个注入项（含 `weather_fn=fake_weather`），所以此处**不能**再传 `weather_fn`，否则 TypeError: multiple values。`from test_planner import _kwargs` 依赖 pytest rootdir 模式把 tests 目录加入 sys.path——M1 测试已验证该模式可用。）

`backend/tests/test_chat.py`：
```python
import pytest
from fastapi.testclient import TestClient

from app import db
from app.graph import build_graph
from app.main import app

from conftest import FakeProvider
from test_planner import _kwargs

`backend/tests/test_chat.py`：
```python
import pytest
from fastapi.testclient import TestClient

from app import db
from app.graph import build_graph
from app.main import app

from conftest import FakeProvider, fake_weather
from test_planner import _kwargs

ITINERARY = {
    "days": [{"day": 1, "title": "熊猫基地", "weather_note": "晴",
              "items": [{"time": "09:00", "name": "宽窄巷子", "poi_id": "chengdu-001", "note": ""}]}],
    "summary": "OK", "warnings": [],
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAVEL_DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    fake = FakeProvider(
        json_responses={
            "已有画像": {
                "destination": "成都", "duration_days": 1, "start_date": None,
                "budget_cny": 8000, "travelers": 2, "preferences": [],
                "missing": [],
            },
            "行程": ITINERARY,
        }
    )
    app.state.graph = build_graph(fake, **_kwargs())  # type: ignore[arg-type]
    app.state.llm_configured = True
    # lifespan="off"：跳过 lifespan（否则无 Key 时 lifespan 会把预设的
    # graph 重置为 None，且 get_provider() 会尝试创建真实 Provider）
    with TestClient(app, lifespan="off") as c:
        yield c
    app.state.graph = None
    app.state.llm_configured = False


def test_chat_returns_reply_and_persists(client):
    resp = client.post("/api/chat", json={"message": "10月去成都玩3天预算8000"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"]
    assert data["reply"].startswith("## ")
    msgs = db.list_messages(data["session_id"])
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[-1]["content"] == data["reply"]


def test_chat_continues_session(client):
    r1 = client.post("/api/chat", json={"message": "10月去成都玩3天预算8000"}).json()
    r2 = client.post("/api/chat", json={"session_id": r1["session_id"], "message": "第二天换成博物馆"})
    assert r2.status_code == 200
    msgs = db.list_messages(r1["session_id"])
    assert len(msgs) == 4


def test_chat_without_llm_returns_503(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAVEL_DB_PATH", str(tmp_path / "nokey.db"))
    db.init_db()
    app.state.graph = None
    app.state.llm_configured = False
    with TestClient(app, lifespan="off") as c:
        resp = c.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 503
    assert "DEEPSEEK_API_KEY" in resp.json()["detail"]
    app.state.graph = None
    app.state.llm_configured = False


def test_chat_empty_message_returns_422(client):
    resp = client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 422
```

`backend/tests/test_sse.py`：**保留 M1 用例，但更新末尾断言**（帧格式把 payload 包进 `data` 字段）：
```python
        # 原断言 payload["ts"] —— 改为：
        payload = json.loads(lines[1].split("data: ", 1)[1])
        assert payload["type"] == "ping"
        assert isinstance(payload["data"]["ts"], float)
```
并在文件顶部补一行 `from app import events`，文件末尾**新增**一个用例（复用文件已有的 `app`、`_scope()` 与 ASGI harness 模式）：
```python
def test_agent_status_flows_through_sse():
    """发布的事件在事件流中可见（直接 ASGI 驱动，与 M1 同款 harness）。"""
    sent = {"type": "agent_status", "data": {"agent": "analyst", "status": "start"}}
    received = {"frames": []}
    done = asyncio.Event()

    async def send(message):
        if message["type"] == "http.response.body":
            frame = message.get("body", b"").decode()
            if not frame:
                return  # 过滤空 body 分块
            received["frames"].append(frame)
            if frame.startswith("event: agent_status"):
                done.set()

    async def runner():
        async with asyncio.timeout(5):
            task = asyncio.create_task(app(_scope(), lambda: None, send))
            # event_stream() 惰性订阅：等 app 跑起来（订阅建立）再发布
            await asyncio.sleep(0.05)
            events.publish(sent)
            await done.wait()
            task.cancel()

    asyncio.run(runner())
    first = next(
        f for f in received["frames"] if f.startswith("event: agent_status")
    )
    assert json.loads(first.split("data: ", 1)[1])["data"]["agent"] == "analyst"
```

- [ ] **Step 2: 实现事件总线与状态模型**

`backend/app/events.py`：
```python
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
```

`backend/app/state.py`（整体替换）：
```python
from typing import Annotated, TypedDict

import operator


class TravelState(TypedDict):
    """Agent 协作共享状态。字段更新采用 reducer 语义（见各字段注释）。"""

    messages: Annotated[list[dict], operator.add]  # 对话历史，累加
    phase: str  # ready / asking / planning / answered
    profile: dict  # 用户画像（Analyst 产出，整体覆盖）
    itinerary: dict  # 结构化行程（Planner 产出，整体覆盖）
    last_reply: str  # 最近一次助手回复文本（聊天 API 读取）
```

- [ ] **Step 3: 实现图装配与聊天 API**

`backend/app/graph.py`（整体替换）：
```python
from functools import partial

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.analyst import analyst_node
from app.agents.planner import planner_node
from app.llm.deepseek import DeepSeekProvider
from app.state import TravelState
from app.rag.retriever import get_poi as _default_get_poi
from app.rag.retriever import normalize_city as _default_normalize_city
from app.rag.retriever import search_nearby as _default_search_nearby
from app.rag.retriever import search_pois as _default_search_pois
from app.tools.weather_api import get_weather as _default_weather


def build_graph(
    llm_provider: DeepSeekProvider,
    *,
    weather_fn=_default_weather,
    search_pois_fn=_default_search_pois,
    search_nearby_fn=_default_search_nearby,
    get_poi_fn=_default_get_poi,
    normalize_city_fn=_default_normalize_city,
) -> CompiledStateGraph:
    """装配双节点图：analyst →（需求齐全时）→ planner → END；
    需求缺失时 analyst 追问后直接 END（等待用户下一轮消息）。

    weather_fn / search_pois_fn 等为 Planner 的依赖注入点
    （测试传 fake 实现，生产用默认真实实现）。"""
    g = StateGraph(TravelState)
    g.add_node("analyst", partial(analyst_node, llm=llm_provider))
    g.add_node(
        "planner",
        partial(
            planner_node,
            llm=llm_provider,
            weather_fn=weather_fn,
            search_pois_fn=search_pois_fn,
            search_nearby_fn=search_nearby_fn,
            get_poi_fn=get_poi_fn,
            normalize_city_fn=normalize_city_fn,
        ),
    )
    g.set_entry_point("analyst")
    g.add_edge("planner", END)
    g.add_conditional_edges(
        "analyst",
        lambda state: "planner" if state.get("phase") == "planning" else END,
        {"planner": "planner", END: END},
    )
    return g.compile()
```

`backend/app/api/chat.py`：
```python
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
```

`backend/app/api/sse.py`（整体替换）：
```python
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app import events

router = APIRouter()


@router.get("/api/events")
async def events_endpoint():
    """SSE 事件流：ping 心跳 + agent_status/itinerary_update 事件。"""
    return StreamingResponse(events.event_stream(), media_type="text/event-stream")
```

`backend/app/main.py`（整体替换）：
```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db
from app.api.chat import router as chat_router
from app.api.sse import router as sse_router
from app.graph import build_graph
from app.llm.deepseek import get_provider

logger = logging.getLogger("travel-agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    try:
        provider = get_provider()
    except RuntimeError as exc:
        # 未配置 DEEPSEEK_API_KEY：应用照常启动，聊天接口返回 503 提示
        app.state.graph = None
        app.state.llm_configured = False
        logger.warning("聊天功能不可用：%s", exc)
    else:
        app.state.graph = build_graph(provider)
        app.state.llm_configured = True
        logger.info("DeepSeek Provider 已配置，图可运行")
    yield


app = FastAPI(title="Travel Agent Backend", version="0.1.0", lifespan=lifespan)
app.state.graph = None
app.state.llm_configured = False

app.include_router(sse_router)
app.include_router(chat_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_events.py tests/test_graph.py tests/test_chat.py tests/test_sse.py -v`
预期：test_events 2 passed + test_graph 2 passed + test_chat 4 passed + test_sse 2 passed。再跑全量 `pytest -v`：全部 PASS。
（`from test_planner import _kwargs` 依赖 tests 目录在 sys.path —— pytest 的 rootdir 模式默认满足；若失败改用 `from conftest` 同款路径处理。）

- [ ] **Step 5: 提交**

```bash
cd /d/agent
git add backend/
git commit -m "feat(backend): SSE 事件总线 + Analyst→Planner 图装配 + 聊天 API

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: 前端联通 + 根 README

**Files:**
- Modify: `frontend/src/api/sse.ts`（ProcessEvent 判别联合 + 统一解析）
- Modify: `frontend/src/components/AgentProcessPanel.tsx`（中文渲染 + 连接状态）
- Modify: `frontend/src/components/ChatPanel.tsx`（onSend 接线）
- Modify: `frontend/src/App.tsx`（消息状态 + 发送 + session 续接）
- Create: `README.md`（仓库根目录）
- Test: 手动验证（M1 惯例：`npm run build` + 双终端联通演示）

**Interfaces:**
- Consumes: `POST /api/chat`（返回 {session_id, reply}）
- Produces: `ProcessEvent` 判别联合；`ChatPanel` props `{onSend, disabled?}`

- [ ] **Step 1: 实现 SSE 客户端判别联合**

`frontend/src/api/sse.ts`（整体替换）：
```ts
export interface PingEvent {
  type: "ping";
  data: { ts: number };
}

export interface AgentStatusEvent {
  type: "agent_status";
  data: { agent: string; status: "start" | "done"; detail?: string };
}

export interface ItineraryEvent {
  type: "itinerary_update";
  data: { itinerary: Record<string, unknown> };
}

export interface ErrorEvent {
  type: "error";
  data: { reason?: string };
}

export type ProcessEvent = PingEvent | AgentStatusEvent | ItineraryEvent | ErrorEvent;

/**
 * 后端帧统一为 {"type": T, "data": {...}}；所有事件类型共用该解析路径，
 * 解包 .data 字段后交给 onEvent。解析失败上报一次 error 事件。
 */
function handle<T>(
  type: ProcessEvent["type"],
  e: Event,
  onEvent: (event: ProcessEvent) => void
): void {
  try {
    const parsed = JSON.parse((e as MessageEvent).data) as { data: T };
    onEvent({ type, data: parsed.data } as ProcessEvent);
  } catch {
    onEvent({ type: "error", data: { reason: "parse" } });
  }
}

/** 连接后端 SSE 事件流，返回断开连接的函数。 */
export function connectSse(
  onEvent: (event: ProcessEvent) => void
): () => void {
  let connected = false;
  const source = new EventSource("/api/events");
  source.addEventListener("ping", (e) =>
    handle<PingEvent["data"]>("ping", e, onEvent)
  );
  source.addEventListener("agent_status", (e) =>
    handle<AgentStatusEvent["data"]>("agent_status", e, onEvent)
  );
  source.addEventListener("itinerary_update", (e) =>
    handle<ItineraryEvent["data"]>("itinerary_update", e, onEvent)
  );
  source.onopen = () => {
    connected = true;
  };
  source.onerror = () => {
    // 仅在连接状态发生转变（已连接 → 断开）时上报一次错误，
    // EventSource 自动重试期间的连续 onerror 不再重复推送。
    if (connected) {
      connected = false;
      onEvent({ type: "error", data: {} });
    }
  };
  return () => source.close();
}
```

- [ ] **Step 2: 实现 Agent 状态面板**

`frontend/src/components/AgentProcessPanel.tsx`（整体替换）：
```tsx
import type { ProcessEvent } from "../api/sse";

const AGENT_NAMES: Record<string, string> = {
  analyst: "需求分析师",
  planner: "行程规划师",
  supervisor: "主管",
};

function describe(e: ProcessEvent): string | null {
  switch (e.type) {
    case "ping":
      return null; // 心跳不展示
    case "agent_status": {
      const name = AGENT_NAMES[e.data.agent] ?? e.data.agent;
      return e.data.status === "start"
        ? `${name} 开始工作${e.data.detail ? `：${e.data.detail}` : ""}…`
        : `${name} 完成`;
    }
    case "itinerary_update":
      return "行程已更新（将在主区域展示）";
    case "error":
      return e.data.reason === "parse" ? "事件解析失败" : "连接中断，正在重连…";
  }
}

interface Props {
  events: ProcessEvent[];
}

export default function AgentProcessPanel({ events }: Props) {
  const visible = events
    .map((e, i) => ({ e, i }))
    .filter(({ e }) => describe(e) !== null);

  return (
    <aside className="w-64 border-l border-slate-200 bg-white p-4 overflow-y-auto">
      <h2 className="text-sm font-semibold text-slate-600 mb-3">Agent 协作</h2>
      {visible.length === 0 && (
        <p className="text-xs text-slate-400">等待事件…</p>
      )}
      <ul className="space-y-1">
        {visible.map(({ e, i }) => (
          <li key={i} className="text-xs text-slate-500">
            {describe(e)}
          </li>
        ))}
      </ul>
    </aside>
  );
}
```

- [ ] **Step 3: 实现聊天面板与回复展示**

`frontend/src/components/ChatPanel.tsx`（整体替换）：
```tsx
import { useState } from "react";

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
}

export default function ChatPanel({ onSend, disabled }: Props) {
  const [text, setText] = useState("");

  const submit = () => {
    const t = text.trim();
    if (!t || disabled) return;
    onSend(t);
    setText("");
  };

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b border-slate-200">
        <p className="text-sm text-slate-500">
          输入出行需求，例如"10月去成都玩3天，预算8000，喜欢美食"
        </p>
      </div>
      <div className="p-3 border-t border-slate-200 flex gap-2 mt-auto">
        <input
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
          placeholder="输入出行需求…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        <button
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50"
          disabled={disabled}
          onClick={submit}
        >
          发送
        </button>
      </div>
    </div>
  );
}
```

`frontend/src/App.tsx`（整体替换）：
```tsx
import { useEffect, useState } from "react";
import AgentProcessPanel from "./components/AgentProcessPanel";
import ChatPanel from "./components/ChatPanel";
import { connectSse, type ProcessEvent } from "./api/sse";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

function App() {
  const [events, setEvents] = useState<ProcessEvent[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  // session_id 在页面会话内持续复用，使"Analyst 追问 → 用户补充回答"的
  // 多轮补全在同一会话内完成（刷新页面则开启新会话）。
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    return connectSse((ev) => setEvents((prev) => [...prev, ev].slice(-50)));
  }, []);

  const handleSend = async (text: string) => {
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setSending(true);
    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => null);
        throw new Error(err?.detail ?? `请求失败 (${resp.status})`);
      }
      const data = await resp.json();
      setSessionId(data.session_id);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.reply },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `⚠️ ${err instanceof Error ? err.message : String(err)}`,
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="h-screen flex bg-slate-50">
      <div className="w-80 border-r border-slate-200 bg-white flex flex-col">
        <ChatPanel onSend={handleSend} disabled={sending} />
      </div>
      <main className="flex-1 p-6 overflow-y-auto">
        <h1 className="text-xl font-bold text-slate-800 mb-4">智能旅行助手</h1>
        {messages.length === 0 ? (
          <p className="text-sm text-slate-500">
            输入出行需求，例如"10月去成都玩3天，预算8000，喜欢美食"。
            行程可视化与地图（M5）将在此区域展示。
          </p>
        ) : (
          <div className="space-y-4">
            {messages.map((m, i) => (
              <div
                key={i}
                className={
                  m.role === "user"
                    ? "text-sm text-slate-700 bg-white rounded-lg p-3 border border-slate-200 ml-16"
                    : "text-sm text-slate-800 bg-white rounded-lg p-4 border border-slate-200 whitespace-pre-wrap"
                }
              >
                {m.content}
              </div>
            ))}
            {sending && (
              <p className="text-xs text-slate-400">Agent 正在协作处理…</p>
            )}
          </div>
        )}
      </main>
      <AgentProcessPanel events={events} />
    </div>
  );
}

export default App;
```

- [ ] **Step 4: 根 README**

`README.md`（仓库根目录，整体新建）：
```markdown
# 智能旅行助手（多 Agent）

多 Agent 协作的智能旅行助手 Web 应用 —— 作品集项目。
用户以自然语言提出出行需求（**支持国内约 20 个旅游城市**），多个专业 Agent 协作完成
行程规划、天气查询与个性化推荐。

架构：**LangGraph supervisor 模式 + 5 个 Agent**（Supervisor / Analyst / Planner / Researcher / Budget），
FastAPI 后端 + React 前端，SSE 实时推送协作过程。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · LangGraph · SQLite · httpx |
| LLM | DeepSeek（OpenAI 兼容，JSON 模式） |
| **RAG 知识库** | **Chroma + BGE（bge-small-zh-v1.5，ModelScope 下载）**，全国约 20 城景点/酒店/餐厅语义检索 |
| 前端 | React 19 · Vite 8 · TypeScript · Tailwind v4 |
| 实时通信 | SSE（ping / agent_status / itinerary_update 事件） |

## 目录结构

```
backend/   FastAPI + LangGraph（agents/ 节点 · rag/ 向量知识库 · tools/ 天气 · llm/ Provider · api/）
frontend/  React 三栏骨架（聊天 / 行程主区域 / Agent 协作面板）
docs/      设计文档与里程碑计划
```

## 快速开始

### 1. 后端

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"     # 含 chromadb/transformers/torch 等 RAG 依赖
export DEEPSEEK_API_KEY=sk-xxx          # DeepSeek 平台申请；配置后聊天功能可用（Git Bash；cmd 用 set）
# 首次运行需准备 RAG 知识库（三步）：
.venv/Scripts/python -m app.rag.download_model   # 1. 下载 BGE 模型（ModelScope，约 95MB）
.venv/Scripts/python -m app.rag.generate        # 2. 生成 20 城 POI 语料（DeepSeek 约 20 次调用）
.venv/Scripts/python -m app.rag.ingest          # 3. 向量化入库（Chroma）
.venv/Scripts/uvicorn app.main:app --port 8000
```

### 2. 前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173（/api 代理到 :8000）
```

浏览器打开 http://localhost:5173，输入"10月去成都玩3天，预算8000，喜欢美食"，
右侧 Agent 协作面板会实时显示各 Agent 的工作状态。

> 语料为 **AI 生成示例数据，坐标仅供参考**；如某城数据不理想，可编辑
> `backend/data/poi_corpus.jsonl` 后重跑 `python -m app.rag.ingest` 增量入库。

## 测试

```bash
cd backend && .venv/Scripts/python -m pytest -v   # 全部用 mock（FakeProvider/FakeEmbedder），无需 API Key、无需模型
```

## 里程碑

| 阶段 | 状态 |
|---|---|
| M1 骨架（FastAPI + SSE + SQLite + 图 + 前端骨架） | ✅ 完成 |
| M2 最小闭环（DeepSeek + **RAG POI 知识库** + Analyst/Planner + 天气） | 🚧 进行中 |
| M3 完整协作（Supervisor 路由 + Researcher/Budget + 并行） | ⬜ |
| M4 对话能力（checkpointer + 修改重排） | ⬜ |
| M5 地图与交付（Leaflet + 可视化 + 文档 + 演示脚本） | ⬜ |

详细设计见 [docs/superpowers/specs/2026-08-19-travel-assistant-design.md](docs/superpowers/specs/2026-08-19-travel-assistant-design.md)
```

- [ ] **Step 5: 验证**

Run: `cd /d/agent/frontend && npm run build`
预期：构建成功（tsc 严格模式下类型通过）。

联通演示（M2 完成标志）：
```bash
# 终端 A（后端，需 DEEPSEEK_API_KEY + RAG 库已入库）
cd /d/agent/backend && export DEEPSEEK_API_KEY=sk-xxx && .venv/Scripts/uvicorn app.main:app --port 8000
# 终端 B（前端）
cd /d/agent/frontend && npm run dev
```
浏览器打开 http://localhost:5173：
1. 输入"10月去成都玩3天，预算8000，喜欢美食"并发送
2. 右侧 Agent 协作面板依次出现「需求分析师 开始工作…」「需求分析师 完成」「行程规划师 开始工作…」「行程规划师 完成」
3. 主区域出现含「第 1 天：…」「第 2 天：…」「第 3 天：…」的中文行程 markdown，景点与周边餐厅来自 RAG 检索
4. 终端 A 无报错；若天气 API 失败，回复末尾出现"模拟数据"脚注

- [ ] **Step 6: 提交**

```bash
cd /d/agent
git add frontend/ README.md
git commit -m "feat(frontend): 聊天收发与 Agent 状态面板联通，新增根 README

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## M2 验证汇总（完成标志）

1. `cd /d/agent/backend && .venv/Scripts/python -m pytest -v` —— 全部 PASS（FakeProvider/FakeEmbedder/fake_weather，无网络、无模型下载）
2. RAG 冒烟（一次性，需网络）：`download_model` → `generate` → `ingest`，`count() ≥ 300`；检索"成都 火锅"命中火锅店
3. `cd /d/agent/frontend && npm run build` —— 构建成功
4. 双终端启动前后端（DEEPSEEK_API_KEY + RAG 库就绪），输入"10月去成都玩3天，预算8000，喜欢美食" → 主区域出现中文天级行程、Agent 面板实时滚动协作状态
5. 会话持久化：同一 session 的第二条消息基于历史规划（test_chat_continues_session 覆盖）
