# M4 对话能力：会话持久化（checkpointer）+ 修改重排

**日期：** 2026-08-20
**里程碑：** M4（对话能力）——M3 已完成（5-agent 并行图 + 34 省 RAG）
**前置：** PR #3 已合并（9b2023e），main 分支 HEAD 9b2023e

## 一、目标

用户与旅行助手之间形成**连续对话**：同一会话内的多轮消息共享同一份用户画像与行程状态；用户提出修改（如"第二天换成博物馆"）后，行程在保留已确认画像（目的地/天数/预算）的前提下**全量重排**。刷新页面/重启服务后会话可恢复。

## 二、决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 重排语义 | **全量重排**（保留画像字段，5 agent 全图重跑） | 用户确认；实现简单、LLM 质量稳定 |
| 持久化范围 | **完整持久化**（sqlite checkpointer + 前端 localStorage + 历史恢复） | 用户确认；演示体验完整 |
| checkpointer 介质 | **langgraph SqliteSaver（同步）**，checkpoint 存 `data/travel.db` | 计划字面（M3 计划"M4 对话能力（checkpointer + 修改重排）"）；与现有 db.py 同库；langgraph 自建表免维护 schema |
| 画像合并 | 复用现有 analyst"已有画像 + null 不覆盖"机制，**不改节点提示词** | analyst.py:64-78 已实现；checkpointer 恢复 `state["profile"]` 后自动生效 |
| 消息存储 | checkpoint 内 messages 为图内部状态；db.py messages 仍为会话历史与前端恢复的数据源 | 职责分离：图状态 vs 用户可见记录 |
| 新依赖 | 无（langgraph 已装；SqliteSaver 为 langgraph.checkpoint.sqlite 内置） | 避免 aiosqlite 异步栈（图在 asyncio.to_thread 同步运行） |

## 三、架构与组件改动

```
┌─────────────┐   POST /api/chat {message, session_id}
│  ChatPanel  │ ───────────────────────────────┐
└─────────────┘                                ▼
        │ localStorage session_id     ┌────────────────────┐
        │ GET /api/chat/history       │ chat.py            │
        ▼                             │  build_graph(...)   │
┌─────────────┐  SSE agent_status     │    .compile(       │
│  AgentPanel │ ◄──────────────────── │      checkpointer) │
└─────────────┘                       └─────────┬──────────┘
                                                │ invoke(config={"configurable":
                                                │   {"thread_id": sid}})
                                                ▼
        ┌─────────── sqlite: data/travel.db ───────────┐
        │ db.py 表: sessions / messages（现状不变）        │
        │ langgraph 表: checkpoints / checkpoint_writes │
        └───────────────────────────────────────────────┘
```

### 后端

1. **graph.py**：`build_graph(...)` 增加可选参数 `checkpointer=None` → `g.compile(checkpointer=checkpointer)`。签名变更向后兼容（默认 None = 现状无状态图，测试隔离）。
2. **chat.py**（核心改造）：
   - invoke 传入 `config={"configurable": {"thread_id": sid}}`（sid 为 `db.create_session()`/请求传入的 session_id）
   - 不再传全量消息历史；`graph.invoke` 初始输入只含**最新一条 user 消息** + `phase: ""`（旧消息/画像/行程由 checkpointer 恢复，`operator.add` 延续）
   - 每次 invoke **新建** SqliteSaver 实例（sqlite3 连接不跨线程共享；`asyncio.to_thread` 工作线程内使用后即弃）
   - 会话不存在（非法 session_id）时退回 `db.create_session()` 新会话
   - db.py 记录行为不变（user 消息 + 最终 reply 落库）
   - 新增端点 `GET /api/chat/history?session_id=` → `{"messages": [{role, content}, ...]}`（前端刷新恢复展示；session 不存在返回 404）
3. **db.py**：无改动（checkpoint 表由 langgraph 自建）。

### 前端（App.tsx）

4. **session 恢复**：session_id 存 `localStorage`（key `travel_session_id`）；页面加载时若有 → 调 `GET /api/chat/history` 恢复消息展示（失败静默忽略，保持空状态）；无 → 保持 null（首次发送时后端创建）
5. 发送逻辑不变（`POST /api/chat` 带 session_id）

### 数据流（修改重排场景）

1. 用户："10月去成都玩3天，预算8000，喜欢美食" → checkpoint 保存 state（profile=成都/3/8000/美食）
2. 用户："第二天换成博物馆" → checkpointer 恢复 profile → analyst 抽取（destination/duration_days/budget_cny = null → **不覆盖**；preferences 由 LLM 抽取合并）→ 全图重跑 → 新行程整体覆盖旧 itinerary
3. 用户刷新页面 → localStorage 取 session_id → history 端点恢复消息 → 继续对话

## 四、错误处理与边界

| 场景 | 行为 |
|---|---|
| checkpoint 表不存在/损坏 | langgraph 首次访问自动建表；损坏时 sqlite 报错 → chat.py 502（现状降级路径，不新增逻辑） |
| 非法 session_id（历史存在但 checkpoint 无记录） | checkpointer 空恢复 → 当新会话处理；db.py 历史仍可读 |
| analyst 追问轮 | 每轮 checkpoint 存 asking 状态；用户补充后恢复继续 ✓ |
| 旧版 checkpoint 状态（M4 前无此机制，不存在迁移问题） | 不适用 |
| 多 worker/多进程 | 超出 M4 范围（单进程 uvicorn 演示）；sqlite 并发写由 WAL 默认关闭的锁机制兜底（演示单用户） |

## 五、测试策略（全部 mock，无网络、无模型下载）

- `test_chat.py` 扩展：
  - 同 thread_id 两次 invoke → 第二次 analyst 收到的提示词含旧画像（fake 断言 prompt 内容含"成都"）
  - 修改重排端到端：第一轮"成都"全流程 → 第二轮"第二天换成博物馆" → 第二轮 fake 按修改语义响应 → 最终 reply 为第二轮新行程，且 state profile 保留成都/3/8000
  - history 端点：session 存在返回消息列表、不存在返回 404
  - 非法 session_id 自动新建
- `test_graph.py`：checkpointer 注入后原有拓扑测试不回归（compile(checkpointer=None) 默认路径）
- 前端：`tsc -b` + `vite build` 通过

## 六、验收演示（controller 手动，最终审查前）

1. 双终端（uvicorn :8000 + vite :5173，真实 DEEPSEEK_API_KEY）
2. 发送"10月去成都玩3天，预算8000，喜欢美食" → 完整行程
3. 发送"第二天换成博物馆" → 新行程：destination 成都 / 3 天 / 预算 8000 保留，第二天含博物馆类景点（真实 LLM 行为，以回复为准验证画像延续）
4. 刷新页面 → 历史消息与 session 恢复 → 再发一条消息仍沿用画像
5. 结果记入 `.superpowers/sdd/progress.md`

## 七、范围外（YAGNI）

- 增量修改（只改提及的天）——已决策全量重排
- 多会话管理 UI / 会话列表
- 多进程 checkpointer 并发（sqlite 单进程演示足够）
- 修改前的行程版本保留（"上一版行程"）
