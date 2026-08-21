# 架构与协作设计

智能旅行助手（多 Agent）—— 技术架构、Agent 协作流程与数据流说明。

## 一、系统架构

```mermaid
flowchart LR
    U[用户浏览器] -->|React 19 + Vite| FE[前端 SPA<br/>聊天 / 地图日卡 / Agent 面板]
    FE -->|POST /api/chat<br/>GET /api/chat/history<br/>GET /api/itinerary| API[FastAPI]
    FE <-.->|SSE: agent_status<br/>itinerary_update| API
    API --> G[LangGraph 状态图<br/>5 Agent 协作]
    G --> LLM[DeepSeek API<br/>JSON 模式]
    G --> RAG[(RAG 知识库<br/>Chroma + BGE<br/>34 省景点)]
    G --> DB[(SQLite data/travel.db<br/>sessions / messages / trip_json<br/>+ langgraph checkpoint 表)]
    API --> DB
```

## 二、Agent 协作流程

```mermaid
sequenceDiagram
    participant U as 用户
    participant C as chat.py
    participant A as Analyst 需求分析师
    participant R as Researcher 研究员
    participant B as Budget 预算官
    participant P as Planner 行程规划师
    participant S as Supervisor 主管
    U->>C: "10月去成都玩3天，预算8000，喜欢美食"
    C->>A: graph.invoke（checkpointer 按 thread_id 恢复画像）
    A->>A: 抽取画像（目的地/天数/预算/偏好）
    A->>C: 画像完整 → phase=planning
    par 并行 fan-out
        C->>R: 三级粒度检索 + 天气
        R->>C: 候选景点（含坐标）+ 逐日天气
    and
        C->>B: 预算分配
        B->>C: 预算表（按总预算约束缩放）
    end
    C->>P: 候选 + 预算 + 天气
    P->>P: 行程 JSON → 幻觉清洗 → 富化坐标
    P->>C: 结构化行程 + 文本回复 + itinerary_update
    C->>S: 行程 + 预算
    S->>C: 汇总建议 + 最终回复
    C->>U: {reply, trip}（trip 落库 trip_json）
```

## 三、数据流（检索 → 富化 → 地图）

```mermaid
flowchart TD
    Q[用户需求] --> AN[Analyst 画像]
    AN -->|destination| RE[Researcher]
    RE --> N{normalize_region<br/>三级粒度}
    N -->|省名| P1[全省景点]
    N -->|库内城市| P2[该市景点]
    N -->|库外城市| P3[fallback 全省]
    P1 & P2 & P3 --> KB[(Chroma 语义检索<br/>top-8 候选含 lat/lng)]
    KB --> PL[Planner 行程 JSON<br/>items 引用 poi_id]
    PL --> EN[enrich_itinerary<br/>按 poi_id 附坐标]
    EN --> ST[(state.itinerary 富化行程)]
    ST --> TR[trip = itinerary<br/>+ budget_plan + summary + tips]
    TR --> DB2[(messages.trip_json)]
    TR --> FE2[前端 TripView]
    DB2 -->|GET /api/itinerary<br/>刷新恢复| FE2
    FE2 --> MAP[Leaflet 地图<br/>高德瓦片 + 每日路线]
    FE2 --> CARDS[日卡 + 预算卡片]
```

## 四、关键设计决策

| 主题 | 决策 | 说明 |
|---|---|---|
| 会话持久化 | LangGraph SqliteSaver（thread_id = session_id） | 多轮对话画像延续；修改需求全图重跑 |
| 坐标来源 | RAG 语料（AI 生成示例数据，坐标仅供参考） | 地图标记仅景点；餐厅/酒店为（示例）条目不上地图 |
| 行程富化 | planner 节点内 enrich_itinerary | 一次 HTTP 往返前端拿到完整 trip |
| 回复文本 | 确定性 format_itinerary | LLM 只产出结构化 JSON，文本不依赖 LLM 措辞 |
| 幻觉防御 | 有 poi_id 且不在候选 → 丢弃 | 防止编造景点渲染成真实行程 |
| 实时协作 | SSE agent_status / itinerary_update | Agent 面板实时滚动各节点状态 |

## 五、目录结构

```
backend/app/
  agents/       5 个 Agent 节点（analyst/researcher/budget/planner/supervisor）
  rag/          RAG（retriever 三级检索 / vector_store / embeddings / ingest / generate）
  itinerary.py  行程富化（poi_id → 坐标）
  graph.py      LangGraph 装配（checkpointer 注入）
  api/          chat / events(SSE) / sse
frontend/src/
  components/   ChatPanel / TripView（地图+日卡）/ ItineraryMap / AgentProcessPanel
  api/          sse（EventSource 封装）
scripts/
  dev.sh        一键启动（--setup 自动准备 RAG）
```
