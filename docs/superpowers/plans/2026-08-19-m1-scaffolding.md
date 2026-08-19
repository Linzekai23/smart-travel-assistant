# M1 骨架搭建 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建前后端可运行骨架，打通 SSE 通道（完成标志：前端收到后端推送的测试事件）。

**Architecture:** 后端 FastAPI 提供 `/api/events` SSE 流与 SQLite 会话存储；LangGraph 空图先行验证编排环境可用；前端 React+Vite+Tailwind 三栏骨架（聊天区/主区域/Agent 协作面板）通过 Vite proxy 连后端 SSE。

**Tech Stack:** Python 3.11, FastAPI, uvicorn, LangGraph, pytest; Node, React 18, Vite 5, Tailwind CSS 4

**Spec:** `docs/superpowers/specs/2026-08-19-travel-assistant-design.md`

## Global Constraints

- 开发平台：Windows 11（Git Bash），后端 venv 用 `.venv/Scripts/python`（Windows）路径调用
- 后端端口 `8000`，前端端口 `5173`，前端通过 Vite proxy 转发 `/api` → `http://localhost:8000`（避免 CORS）
- UI 文案使用简体中文
- Python 依赖下限：fastapi>=0.115, langgraph>=0.2, pydantic>=2.7, pytest>=8.0, httpx>=0.27
- 所有后端命令在 `backend/` 目录下执行（pytest 的 `testpaths=["tests"]` 依赖此根目录）
- 每任务结束必须提交（frequent commits 原则）
- 所有 git commit 信息以 `Co-Authored-By: Claude <noreply@anthropic.com>` 结尾（两行：信息 + 空行 + 该行）

---

### Task 1: 后端骨架（pyproject + FastAPI 健康检查）

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`（空文件）
- Create: `backend/app/main.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Produces: `app.main.app`（FastAPI 实例），`GET /api/health` → `{"status": "ok"}`

- [ ] **Step 1: 创建依赖清单与骨架文件**

`backend/pyproject.toml`：
```toml
[project]
name = "travel-agent-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "langgraph>=0.2",
    "pydantic>=2.7",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

创建 `backend/app/__init__.py`（空）、`backend/app/main.py`：
```python
from fastapi import FastAPI

app = FastAPI(title="Travel Agent Backend", version="0.1.0")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 2: 建 venv 并安装依赖**

```bash
cd /d/agent/backend
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install -e ".[dev]"
```
预期：安装成功，无报错。

- [ ] **Step 3: 写失败测试**

`backend/tests/test_health.py`：
```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 4: 运行测试验证失败/通过**

```bash
.venv/Scripts/python -m pytest tests/test_health.py -v
```
预期：PASS（main.py 已写好，测试可直接通过 —— 这是骨架任务的正常形态）。

- [ ] **Step 5: 提交**

```bash
git add backend/
git commit -m "feat(backend): FastAPI 骨架与健康检查"
```

---

### Task 2: SSE ping 事件流端点

**Files:**
- Create: `backend/app/api/__init__.py`（空文件）
- Create: `backend/app/api/sse.py`
- Modify: `backend/app/main.py`（挂载 router）
- Test: `backend/tests/test_sse.py`

**Interfaces:**
- Consumes: `app.main.app`
- Produces: `GET /api/events` — SSE 流，每 1 秒推一条命名事件 `ping`，payload 为 JSON `{"type": "ping", "ts": <unix秒>}`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_sse.py`：
```python
import json
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_sse_emits_ping_events():
    with client.stream("GET", "/api/events") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        first = resp.iter_lines().__next__()
        assert first == "event: ping"
        data_line = resp.iter_lines().__next__()
        assert data_line.startswith("data: ")
        payload = json.loads(data_line.split("data: ", 1)[1])
        assert payload["type"] == "ping"
        assert isinstance(payload["ts"], float)
```
预期：FAIL —— `ImportError: cannot import name 'sse' from 'app.api'` 或 404。

- [ ] **Step 2: 实现 SSE 端点**

`backend/app/api/sse.py`：
```python
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
```

`backend/app/main.py` 增加挂载（在 `app = FastAPI(...)` 之后）：
```python
from app.api.sse import router as sse_router

app.include_router(sse_router)
```

- [ ] **Step 3: 运行测试验证通过**

```bash
.venv/Scripts/python -m pytest tests/test_sse.py -v
```
预期：PASS。若 `iter_lines()` 卡住（事件未及时刷出），检查是否缺少 `\n\n` 事件分隔符。

- [ ] **Step 4: 提交**

```bash
git add backend/
git commit -m "feat(backend): SSE ping 事件流端点"
```

---

### Task 3: SQLite 会话与消息存储层

**Files:**
- Create: `backend/app/db.py`
- Test: `backend/tests/test_db.py`

**Interfaces:**
- Produces: `init_db()` / `create_session() -> str` / `get_session(sid) -> dict | None` / `add_message(sid, role, content)` / `list_messages(sid) -> list[dict]`
- 数据库路径由环境变量 `TRAVEL_DB_PATH` 控制（测试注入临时路径，默认 `data/travel.db`）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_db.py`：
```python
import os

import pytest

from app import db


@pytest.fixture()
def tmp_db(tmp_path):
    os.environ["TRAVEL_DB_PATH"] = str(tmp_path / "test.db")
    db.init_db()
    yield
    del os.environ["TRAVEL_DB_PATH"]


def test_create_and_get_session(tmp_db):
    sid = db.create_session()
    assert db.get_session(sid)["id"] == sid


def test_get_unknown_session_returns_none(tmp_db):
    assert db.get_session("nope") is None


def test_message_roundtrip(tmp_db):
    sid = db.create_session()
    db.add_message(sid, "user", "10月去东京3天预算8000")
    db.add_message(sid, "assistant", "好的，正在规划")
    msgs = db.list_messages(sid)
    assert msgs == [
        {"role": "user", "content": "10月去东京3天预算8000"},
        {"role": "assistant", "content": "好的，正在规划"},
    ]
```
预期：FAIL —— `ImportError`（模块不存在）。

- [ ] **Step 2: 实现 db 模块**

`backend/app/db.py`：
```python
import os
import sqlite3
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_conn() -> sqlite3.Connection:
    path = Path(os.environ.get("TRAVEL_DB_PATH", "data/travel.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def create_session() -> str:
    sid = uuid.uuid4().hex
    conn = get_conn()
    try:
        conn.execute("INSERT INTO sessions (id) VALUES (?)", (sid,))
        conn.commit()
    finally:
        conn.close()
    return sid


def get_session(sid: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def add_message(sid: str, role: str, content: str) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (sid, role, content),
        )
        conn.commit()
    finally:
        conn.close()


def list_messages(sid: str) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
            (sid,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
```

- [ ] **Step 3: 运行测试验证通过**

```bash
.venv/Scripts/python -m pytest tests/test_db.py -v
```
预期：PASS（3 个用例）。

- [ ] **Step 4: 提交**

```bash
git add backend/
git commit -m "feat(backend): SQLite 会话与消息存储层"
```

---

### Task 4: LangGraph 空图（状态模型 + 可编译图）

**Files:**
- Create: `backend/app/state.py`
- Create: `backend/app/graph.py`
- Test: `backend/tests/test_graph.py`

**Interfaces:**
- Produces: `app.state.TravelState`（TypedDict：`messages: Annotated[list[dict], operator.add]`、`phase: str`）；`app.graph.graph`（已编译的 StateGraph，invoke 后 `phase == "ready"`）
- 后续任务依赖 `TravelState` 的字段名，后续节点通过返回部分 dict 更新状态

- [ ] **Step 1: 写失败测试**

`backend/tests/test_graph.py`：
```python
from app.graph import graph


def test_empty_graph_runs():
    result = graph.invoke({"messages": [], "phase": ""})
    assert result["phase"] == "ready"
```
预期：FAIL —— `ImportError`。

- [ ] **Step 2: 实现状态模型与空图**

`backend/app/state.py`：
```python
from typing import Annotated, TypedDict

import operator


class TravelState(TypedDict):
    """Agent 协作共享状态。字段更新采用 reducer 语义（见各字段注释）。"""

    messages: Annotated[list[dict], operator.add]  # 对话历史，累加
    phase: str  # 当前阶段（ready / planning / answered / ...）
```

`backend/app/graph.py`：
```python
from langgraph.graph import END, StateGraph

from app.state import TravelState


def stub_node(state: TravelState) -> dict:
    """M1 占位节点：仅标记图可运行，后续里程碑替换为真实 Agent 节点。"""
    return {"phase": "ready"}


def build_graph():
    g = StateGraph(TravelState)
    g.add_node("stub", stub_node)
    g.set_entry_point("stub")
    g.add_edge("stub", END)
    return g.compile()


graph = build_graph()
```

- [ ] **Step 3: 运行测试验证通过**

```bash
.venv/Scripts/python -m pytest tests/test_graph.py -v
```
预期：PASS。若 langgraph 安装报错，检查 pyproject 依赖已安装（`pip install -e ".[dev]"` 重跑）。

- [ ] **Step 4: 提交**

```bash
git add backend/
git commit -m "feat(backend): LangGraph 空图可运行"
```

---

### Task 5: 前端脚手架（Vite + React + Tailwind + proxy）

**Files:**
- Create: `frontend/`（Vite react-ts 模板 + 安装 tailwind）
- Modify: `frontend/vite.config.ts`（tailwind 插件 + /api 代理）
- Modify: `frontend/src/index.css`（引入 tailwind）
- Modify: `frontend/src/App.tsx`（清空为占位页）

**Interfaces:**
- Produces: 可在 `5173` 端口启动的 React 应用；`/api` 请求代理到 `http://localhost:8000`

- [ ] **Step 1: 生成 Vite 项目并安装依赖**

```bash
cd /d/agent
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install tailwindcss @tailwindcss/vite
```

- [ ] **Step 2: 配置 Tailwind 与代理**

`frontend/vite.config.ts`（整体替换）：
```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
```

`frontend/src/index.css`（整体替换）：
```css
@import "tailwindcss";
```

`frontend/src/App.tsx`（整体替换为占位）：
```tsx
function App() {
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center">
      <h1 className="text-2xl font-bold text-slate-800">智能旅行助手</h1>
    </div>
  );
}

export default App;
```

- [ ] **Step 3: 验证构建与代理**

```bash
cd /d/agent/frontend
npm run build
```
预期：构建成功。另起一个终端启动后端（`cd /d/agent/backend && .venv/Scripts/uvicorn app.main:app --port 8000`），再启动前端 `npm run dev`，浏览器打开 `http://localhost:5173` 应显示"智能旅行助手"。

- [ ] **Step 4: 提交**

```bash
git add frontend/
git commit -m "feat(frontend): Vite+React+Tailwind 脚手架与 /api 代理"
```

---

### Task 6: 前端 SSE 客户端与三栏骨架（联通验证）

**Files:**
- Create: `frontend/src/api/sse.ts`
- Create: `frontend/src/components/AgentProcessPanel.tsx`
- Create: `frontend/src/components/ChatPanel.tsx`
- Modify: `frontend/src/App.tsx`（三栏布局 + 连接状态）
- Test: 手动验证（M1 前端不引入测试框架，验证 = build + 页面连通）

**Interfaces:**
- Produces: `connectSse(onEvent: (event: { type: string; data: unknown }) => void): () => void`（返回断开函数）
- Produces: `AgentProcessPanel` 组件（props: `events: ProcessEvent[]`），`ChatPanel` 占位组件

- [ ] **Step 1: 实现 SSE 客户端**

`frontend/src/api/sse.ts`：
```ts
export interface ProcessEvent {
  type: string;
  data: Record<string, unknown>;
}

/** 连接后端 SSE 事件流，返回断开连接的函数。 */
export function connectSse(
  onEvent: (event: ProcessEvent) => void
): () => void {
  const source = new EventSource("/api/events");
  source.addEventListener("ping", (e) => {
    onEvent({ type: "ping", data: JSON.parse((e as MessageEvent).data) });
  });
  source.onerror = () => {
    onEvent({ type: "error", data: {} });
  };
  return () => source.close();
}
```

- [ ] **Step 2: 实现 Agent 协作面板与聊天占位**

`frontend/src/components/AgentProcessPanel.tsx`：
```tsx
export interface ProcessEvent {
  type: string;
  data: Record<string, unknown>;
}

interface Props {
  events: ProcessEvent[];
}

export default function AgentProcessPanel({ events }: Props) {
  return (
    <aside className="w-64 border-l border-slate-200 bg-white p-4 overflow-y-auto">
      <h2 className="text-sm font-semibold text-slate-600 mb-3">Agent 协作</h2>
      {events.length === 0 && (
        <p className="text-xs text-slate-400">等待事件…</p>
      )}
      <ul className="space-y-1">
        {events.map((ev, i) => (
          <li key={i} className="text-xs text-slate-500 font-mono">
            {ev.type === "ping"
              ? `已连接 (t=${String(ev.data.ts)})`
              : `${ev.type}: ${JSON.stringify(ev.data)}`}
          </li>
        ))}
      </ul>
    </aside>
  );
}
```

`frontend/src/components/ChatPanel.tsx`：
```tsx
import { useState } from "react";

export default function ChatPanel() {
  const [text, setText] = useState("");
  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 p-4 overflow-y-auto">
        <p className="text-sm text-slate-500">输入出行需求，例如"10月去东京玩3天，预算8000，喜欢美食"</p>
      </div>
      <div className="p-3 border-t border-slate-200 flex gap-2">
        <input
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
          placeholder="输入出行需求…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white">
          发送
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: 组装三栏布局**

`frontend/src/App.tsx`（整体替换）：
```tsx
import { useEffect, useState } from "react";
import AgentProcessPanel, { ProcessEvent } from "./components/AgentProcessPanel";
import ChatPanel from "./components/ChatPanel";
import { connectSse } from "./api/sse";

function App() {
  const [events, setEvents] = useState<ProcessEvent[]>([]);

  useEffect(() => {
    return connectSse((ev) => setEvents((prev) => [...prev, ev].slice(-50)));
  }, []);

  return (
    <div className="h-screen flex bg-slate-50">
      <div className="w-80 border-r border-slate-200 bg-white">
        <ChatPanel />
      </div>
      <main className="flex-1 p-6 overflow-y-auto">
        <h1 className="text-xl font-bold text-slate-800 mb-4">智能旅行助手</h1>
        <p className="text-sm text-slate-500">
          主区域：行程可视化（M6 实现）。当前显示实时 Agent 协作面板的连通状态。
        </p>
      </main>
      <AgentProcessPanel events={events} />
    </div>
  );
}

export default App;
```

- [ ] **Step 4: 联通验证（M1 完成标志）**

```bash
cd /d/agent/frontend && npm run build
```
预期：构建成功。

终端 A（后端）：`cd /d/agent/backend && .venv/Scripts/uvicorn app.main:app --port 8000`
终端 B（前端）：`cd /d/agent/frontend && npm run dev`

浏览器打开 `http://localhost:5173`：
1. 页面显示三栏布局（聊天 / 主区域 / Agent 协作）
2. Agent 协作面板每秒追加一条"已连接 (t=...)" —— **SSE 通道打通 ✓**
3. 后端终端无 CORS 报错（proxy 生效）

- [ ] **Step 5: 提交**

```bash
git add frontend/
git commit -m "feat(frontend): SSE 客户端与三栏骨架，联通后端事件流"
```

---

## M1 验证汇总

1. `cd /d/agent/backend && .venv/Scripts/python -m pytest -v` —— 全部 PASS
2. 双终端启动前后端，浏览器看到 Agent 协作面板实时滚动"已连接"事件
3. `git log --oneline` 显示 6 个任务提交（骨架/SSE/DB/图/前端脚手架/联通）
