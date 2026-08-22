# M4 对话能力（checkpointer 持久化 + 修改重排）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 会话内多轮共享画像与行程状态；用户提出修改后全量重排（保留已确认画像字段）；刷新/重启后会话可恢复。

**Architecture:** langgraph SqliteSaver checkpointer（`thread_id = session_id`，checkpoint 存 `data/travel.db` 与 db.py 同库不同表）；chat.py 每请求新建图实例（build_graph + checkpointer，sqlite 连接不跨线程共享）；analyst 现有"已有画像 + null 不覆盖"机制负责画像延续；前端 localStorage + 新 history 端点恢复会话。

**Tech Stack:** langgraph 1.2.11 + langgraph-checkpoint-sqlite 3.1.1（新依赖，已安装）、FastAPI、sqlite3、React 19 + Vite。

**Spec:** docs/superpowers/specs/2026-08-20-m4-conversation-design.md（计划从此 spec 论证）

## Global Constraints

- 每个 commit 以 `Co-Authored-By: Claude <noreply@anthropic.com>` 结尾
- 测试全部 mock（FakeProvider / fake_weather / fake search，无网络、无模型下载）
- checkpointer 介质：`langgraph.checkpoint.sqlite.SqliteSaver`，连接用 `sqlite3.connect(path, check_same_thread=False)`，**每次请求新建实例**（asyncio.to_thread 线程池下不跨线程共享连接）
- checkpoint 与 db.py 同库：path = `os.environ.get("TRAVEL_DB_PATH", "data/travel.db")`，parent mkdir
- `graph.invoke` 初始输入**只含最新一条 user 消息** + `phase: ""`；旧消息/画像/行程由 checkpointer 恢复（operator.add 延续），绝不传全量历史（否则消息重复）
- 重排语义为**全量重排**：节点全部重跑，画像字段由 analyst 的"已有画像 + null 不覆盖"延续（analyst.py 提示词与节点逻辑不改动）
- 前端 localStorage key 固定为 `travel_session_id`；history 端点失败静默降级（保持空状态）
- 生产路径 `build_graph(provider, checkpointer=...)` 每请求构建（图装配开销 ≪ LLM 调用）；`app.state.graph` 不再使用（503 检查改用 `app.state.provider is None`）
- spec 的"新依赖：无"条目修正为：langgraph-checkpoint-sqlite 3.1.1（langgraph 1.x 将 SqliteSaver 拆分为独立官方包）
- 不做 M3 Minor 修复（m3-minor-triage.md 全部 defer），除本计划任务内必要者

---

### Task 1: graph.py 注入 checkpointer 参数

**Files:**
- Modify: `backend/app/graph.py`（build_graph 签名 + compile 透传）
- Test: `backend/tests/test_graph.py`

**Interfaces:**
- Produces: `build_graph(llm_provider, *, weather_fn, search_pois_fn, normalize_region_fn, checkpointer=None) -> CompiledStateGraph`——`compile(checkpointer=checkpointer)`；默认 None = 现状无状态图（既有测试零改动）
- Consumes: 无（纯透传）

- [ ] **Step 1: Write the failing test** — `backend/tests/test_graph.py` 追加：

```python
def test_build_graph_accepts_checkpointer():
    """compile(checkpointer=...) 注入后状态跨 invoke 延续（同一 thread_id）。"""
    from langgraph.checkpoint.memory import MemorySaver

    fake = _fake()
    graph = build_graph(fake, checkpointer=MemorySaver(), **_researcher_kwargs())
    cfg = {"configurable": {"thread_id": "t1"}}
    r1 = graph.invoke({"messages": [{"role": "user", "content": "10月去广州玩3天，预算8000"}], "phase": ""}, config=cfg)
    assert r1["profile"]["destination"] == "广州"
    r2 = graph.invoke({"messages": [{"role": "user", "content": "第二天换成博物馆"}], "phase": ""}, config=cfg)
    # 第二次 analyst 提示词应含已有画像（画像跨 invoke 延续）
    assert "已有画像" in fake.calls[-1][-1]["content"]
    assert "广州" in fake.calls[-1][-1]["content"]
```

（`_fake`/`_researcher_kwargs` 沿用文件内现有 helper；`_fake()` 的 json_responses 必须覆盖全部 5 个标记词——按现有 `test_full_planning_flow` 样式。）

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_graph.py::test_build_graph_accepts_checkpointer -v`
Expected: FAIL——`build_graph(...)` 不接受 `checkpointer` 关键字（TypeError）

- [ ] **Step 3: Write minimal implementation** — `backend/app/graph.py`：

```python
def build_graph(
    llm_provider: DeepSeekProvider,
    *,
    weather_fn=_default_weather,
    search_pois_fn=_default_search_pois,
    normalize_region_fn=_default_normalize_region,
    checkpointer=None,
) -> CompiledStateGraph:
    """装配 5 节点图：analyst → ‖researcher‖budget‖ → planner → supervisor → END。

    需求缺失时 analyst 追问后直接 END（等待用户下一轮消息）。
    weather_fn / search_pois_fn / normalize_region_fn 为 Researcher 的依赖注入点
    （测试传 fake 实现，生产用默认真实实现）。
    checkpointer：langgraph checkpointer（如 SqliteSaver/MemorySaver），
    传入后同 thread_id 的多次 invoke 自动恢复/延续 state（M4 对话能力）。"""
    ...（中间不变）...
    return g.compile(checkpointer=checkpointer)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_graph.py -v`
Expected: 全绿（原 4 个测试 + 新 1 个）

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph.py backend/tests/test_graph.py
git commit -m "feat: build_graph accepts checkpointer injection (M4 conversation base)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: chat.py 接入 checkpointer（多轮延续 + 修改重排）

**Files:**
- Modify: `backend/app/main.py`（lifespan 存 provider 替代 graph）
- Modify: `backend/app/api/chat.py`（每请求构建带 checkpointer 的图；只传最新消息）
- Test: `backend/tests/test_chat.py`（fixture 改造 + 3 个新用例）

**Interfaces:**
- Consumes: Task 1 的 `build_graph(..., checkpointer=None)`；`app.llm.deepseek.get_provider`（main.py 现状）
- Produces:
  - `app.state.provider: DeepSeekProvider | None`（lifespan 设置；None = 未配置 → 503）
  - chat.py 内部 `_new_checkpointer() -> SqliteSaver`、`_graph_for_request(request) -> CompiledStateGraph`
  - 行为契约：`POST /api/chat` 请求体/响应不变；invoke config `{"configurable": {"thread_id": sid}}`
  - db.py 记录行为不变（user + 最终 reply）

**测试注意**：FakeProvider 为子串匹配——第二轮"第二天换成博物馆"时 analyst 提示词含"已有画像"→ 命中"已有画像"键返回广州画像（destination/duration/budget 延续），其余节点照常命中各自标记词。**不需要新增 json_responses 键**。

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_chat.py`

先改 client fixture（provider 注入替代 graph 注入）：

```python
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAVEL_DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    fake = FakeProvider(
        json_responses={...同现有 5 键，一字不改...},
    )
    app.state.graph = None
    app.state.llm_configured = False
    # lifespan 用 get_provider 构建 provider（chat.py 每请求再 build 带 checkpointer 的图）
    def _fake_provider():
        return fake
    monkeypatch.setattr("app.main.get_provider", _fake_provider)
    with TestClient(app) as c:
        yield c
    app.state.graph = None
    app.state.llm_configured = False
```

（`_no_real_provider` autouse fixture 保留不动——lifespan 内 `get_provider` 已被 monkeypatch 到 fixture 级别。注意 autouse 的 `_raise` 会在 client fixture 的 monkeypatch 之前执行？两者都 monkeypatch `app.main.get_provider`——fixture 顺序：autouse 先于显式 fixture 执行，显式 `_fake_provider` 后设生效 ✓。lifespan 在 TestClient 上下文进入时执行，此时 get_provider = _fake_provider ✓。）

新增用例：

```python
def test_chat_second_round_keeps_profile(client):
    """checkpointer 延续画像：第二轮 analyst 提示词含旧画像，回复为第二轮行程。"""
    r1 = client.post("/api/chat", json={"message": "10月去广州玩3天预算8000"}).json()
    r2 = client.post("/api/chat", json={"session_id": r1["session_id"], "message": "第二天换成博物馆"})
    assert r2.status_code == 200
    assert r2.json()["session_id"] == r1["session_id"]
    assert r2.json()["reply"].startswith("## ")
    # 全部 fake LLM 调用中，analyst（含"已有画像"的提示词）最后一次应带旧画像
    analyst_prompts = [c for c in client.app.state.provider.calls if "已有画像" in c[-1]["content"]]
    assert len(analyst_prompts) == 2
    assert "广州" in analyst_prompts[-1][-1]["content"]
    assert "8000" in analyst_prompts[-1][-1]["content"]


def test_chat_replan_produces_new_reply(client):
    """第二轮全量重排：回复为第二轮行程（新 itinerary），非旧回复。"""
    r1 = client.post("/api/chat", json={"message": "10月去广州玩3天预算8000"}).json()
    r2 = client.post("/api/chat", json={"session_id": r1["session_id"], "message": "第二天换成博物馆"})
    assert r2.json()["reply"] != r1["reply"]


def test_chat_unknown_session_creates_new(client):
    """非法 session_id → 后端按新会话处理（不崩溃）。"""
    resp = client.post("/api/chat", json={"session_id": "deadbeef", "message": "10月去广州玩3天预算8000"})
    assert resp.status_code == 200
    assert resp.json()["session_id"] != "deadbeef"
```

（`client.app.state.provider` 需可用——TestClient.app 暴露 FastAPI app。）

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_chat.py -v`
Expected: FAIL——新用例断言失败（未接 checkpointer 时第二轮 analyst 提示词无旧画像 / session 不延续）。现有用例可能因 fixture 改动受影响（`app.state.graph` 不再被 chat.py 使用）——预期 `test_chat_returns_reply_and_persists` 等失败（chat.py 读 `request.app.state.graph` 仍存在则继续工作；实现后统一恢复）。

- [ ] **Step 3: Write the implementation**

`backend/app/main.py`（lifespan）：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    try:
        provider = get_provider()
    except RuntimeError as exc:
        # 未配置 DEEPSEEK_API_KEY：应用照常启动，聊天接口返回 503 提示
        app.state.provider = None
        app.state.llm_configured = False
        logger.warning("聊天功能不可用：%s", exc)
    else:
        app.state.provider = provider
        app.state.llm_configured = True
        logger.info("DeepSeek Provider 已配置，图可运行")
    yield


app = FastAPI(title="Travel Agent Backend", version="0.1.0", lifespan=lifespan)
app.state.provider = None
app.state.llm_configured = False
```

（`app.state.graph` 全删除——chat.py 不再读它。`build_graph` import 移到 chat.py。）

`backend/app/api/chat.py`（重写，逻辑全保留仅改图构建与 invoke）：

```python
"""聊天 API：POST /api/chat —— 会话持久化 + 图调用 + 回复；GET /api/chat/history —— 历史恢复。"""
import asyncio
import os
import sqlite3

from fastapi import APIRouter, HTTPException, Request
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel, Field

from app import db, events  # noqa: F401  # events 保持导入（graph 节点经 events 发布）
from app.graph import build_graph

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)


def _new_checkpointer() -> SqliteSaver:
    """每次请求新建 SqliteSaver（独立 sqlite 连接，asyncio.to_thread 线程池下不跨线程共享）。"""
    path = Path(os.environ.get("TRAVEL_DB_PATH", "data/travel.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def _graph_for_request(request: Request):
    """每请求构建带 checkpointer 的图实例（图装配开销 ≪ LLM 调用）。"""
    provider = request.app.state.provider
    return build_graph(provider, checkpointer=_new_checkpointer())


@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    provider = request.app.state.provider
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail="DEEPSEEK_API_KEY 未配置：请在环境变量中设置后重启后端",
        )

    sid = req.session_id or db.create_session()
    if db.get_session(sid) is None:
        # 非法/未知 session_id：按新会话处理（历史仍在则继续累积到该 id）
        sid = db.create_session()
    db.add_message(sid, "user", req.message)

    try:
        graph = _graph_for_request(request)
        # M4：checkpointer 按 thread_id=session_id 恢复旧 state（画像/行程/消息）；
        # 初始输入只含最新一条 user 消息，绝不传全量历史（operator.add 会重复累积）。
        result = await asyncio.to_thread(
            graph.invoke,
            {"messages": [{"role": "user", "content": req.message}], "phase": ""},
            config={"configurable": {"thread_id": sid}},
        )
    except Exception as exc:  # LLM/图异常不落库，向前端返回 502
        raise HTTPException(status_code=502, detail=f"行程规划失败: {exc}") from exc

    reply = result.get("last_reply")
    if reply is None and result.get("messages"):
        reply = result["messages"][-1].get("content")
    if reply is None:
        reply = "抱歉，本次没有生成回复。"
    db.add_message(sid, "assistant", reply)
    return {"session_id": sid, "reply": reply}


@router.get("/api/chat/history")
async def history(session_id: str):
    if db.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "messages": db.list_messages(session_id)}
```

（`from pathlib import Path` 需要加在 import 区；`events` 保留导入以防节点循环导入依赖——若 lint 报未使用可删，但先保留。）若 `build_graph` 每请求构建导致测试注入困难，测试通过 monkeypatch `app.main.get_provider` 控制 provider——见 Step 1 fixture。

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_chat.py tests/test_graph.py -v`
Expected: 全绿（test_chat 现有 4 用例改造后 + 3 新用例 + test_graph 5 用例）

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/app/api/chat.py backend/tests/test_chat.py
git commit -m "feat: chat API checkpointer integration — thread_id session state + replan continuity

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 前端会话恢复（localStorage + history 加载）

**Files:**
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Task 2 的 `GET /api/chat/history?session_id=` → `{"session_id", "messages": [{role, content}]}`；`POST /api/chat` 不变
- Produces: 刷新页面后恢复 session_id 与历史消息；发送成功后持久化 session_id

- [ ] **Step 1: Write the failing test**（前端无单测设施，验证方式 = tsc + build 通过 + 手动行为）

本任务无独立测试框架；以类型检查与构建为门禁（Step 2/4）。

- [ ] **Step 2: Run tsc to verify current state**

Run: `cd frontend && npx tsc -b`
Expected: 0 errors（基线）

- [ ] **Step 3: Write the implementation** — `frontend/src/App.tsx`：

```tsx
const SESSION_KEY = "travel_session_id";

function App() {
  const [events, setEvents] = useState<ProcessEvent[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  // session_id 持久化到 localStorage：刷新页面后恢复会话（历史消息 + 画像延续）
  const [sessionId, setSessionId] = useState<string | null>(
    () => localStorage.getItem(SESSION_KEY),
  );
  const [sending, setSending] = useState(false);

  useEffect(() => {
    return connectSse((ev) => setEvents((prev) => [...prev, ev].slice(-50)));
  }, []);

  // 刷新后恢复历史消息；失败（后端未启动/会话过期）静默降级为空会话
  useEffect(() => {
    const sid = localStorage.getItem(SESSION_KEY);
    if (!sid) return;
    fetch(`/api/chat/history?session_id=${encodeURIComponent(sid)}`)
      .then((resp) => (resp.ok ? resp.json() : null))
      .then((data) => {
        if (data?.messages?.length) setMessages(data.messages);
      })
      .catch(() => {});
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
      localStorage.setItem(SESSION_KEY, data.session_id);
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

  // ...render 部分不变
}
```

（`useState` 初始值用函数形式读取 localStorage；仅 3 处改动：SESSION_KEY、useState 初始值、恢复 useEffect、handleSend 内 setItem。其余 JSX 一字不改。）

- [ ] **Step 4: Run tsc + build to verify**

Run: `cd frontend && npx tsc -b && npm run build`
Expected: tsc 0 errors + vite build 成功

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: frontend session persistence — localStorage session_id + history restore

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: README 更新 + 冒烟（controller 手动执行）

**Files:**
- Modify: `README.md`

**代码部分（implementer）**：

- [ ] **Step 1: README 更新**
  - 里程碑表 M4 行：`| M4 对话能力（checkpointer + 修改重排） | ⬜ |` → `| M4 对话能力（会话持久化 + 修改重排） | ✅ 完成 |`
  - 演示段落补充修改重排示例：发送"第二天换成博物馆"→ 保留目的地/天数/预算，重排完整新行程；刷新页面可继续对话
  - 依赖说明新增 langgraph-checkpoint-sqlite（如 README 有依赖清单）

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README — M4 milestone done, conversation demo copy

Co-Authored-By: Claude <noreply@anthropic.com>"
```

**冒烟清单（controller 在本任务完成后、最终审查前手动执行；DEEPSEEK_API_KEY 只经环境变量传递，绝不落盘/打印）**：

1. 双终端：uvicorn :8000（backend/.venv）+ vite :5173（frontend）
2. `POST /api/chat` "10月去成都玩3天，预算8000，喜欢美食" → 完整行程（回复 A）
3. 同 session 再发"第二天换成博物馆" → 回复 B：与 A 不同；真实 LLM 行为下 destination/天数/预算应延续（以回复与前端表现为准）
4. 浏览器刷新 → 历史消息恢复（history 端点）→ 再发消息仍沿用画像
5. `GET /api/chat/history?session_id=<r1>` → 4 条消息（user/assistant × 2）
6. 结果记入 `.superpowers/sdd/progress.md`

---

## 执行顺序与分支

- 分支：`feat/m4-conversation`（从当前 main 创建，main HEAD 含 spec e398535）
- 任务顺序：1 → 2 → 3 → 4；每任务 implementer → task reviewer → ledger；全部完成后最终 whole-branch review（opus）→ 修复波 → push → PR #4
- 模型建议：Task 1/3 为机械实现（计划含完整代码）→ 最便宜档；Task 2/4 为集成/多文件 → 标准档；Task 4 冒烟由 controller 手动执行；最终 whole-branch review → 最贵档
- Task 2 完成后全量回归一次（98 + 新增）
