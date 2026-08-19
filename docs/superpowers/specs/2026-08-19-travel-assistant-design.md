# 智能旅行助手（多 Agent）设计文档

- 日期：2026-08-19
- 状态：已确认（与用户逐块评审通过）
- 定位：作品集项目 —— 展示多 Agent 协作、RAG、LLM 应用工程能力

## 1. 目标与背景

构建一个多 Agent 结构的智能旅行助手 Web 应用。用户以自然语言提出出行需求，系统通过多个专业 Agent 协作完成行程规划、预算分配、实时信息查询、个性化推荐与攻略问答。核心设计原则：**每个 Agent 职责单一、通过 LangGraph supervisor 模式协作、协作过程对用户可见**。

## 2. 设计决策

| 维度 | 决策 | 理由 |
|---|---|---|
| 产品形态 | Web 应用（React + Vite / FastAPI） | 作品集可演示性最强 |
| 编排框架 | LangGraph supervisor 模式 | 业界标准、自带状态管理与可视化、面试可迁移 |
| LLM | DeepSeek（OpenAI 兼容接口） | 国内直连、成本低、兼容性好 |
| 天气数据 | 真实天气 API 适配器 | 真实感；失败时降级模拟数据并标注 |
| POI 数据 | 模拟 POI 库（3-4 城市） | 免平台密钥；接口层抽象以便未来替换 |
| 攻略知识 | RAG 知识库（LLM 自举生成 + BGE + Chroma） | 提升回答可信度，展示完整 RAG 管线 |
| 会话持久化 | SQLite + LangGraph checkpointer | 多轮对话与行程修改的基础 |
| 实时反馈 | SSE 流式推送 Agent 协作过程 | 演示最亮眼的部分 |
| 地图 | Leaflet + react-leaflet | 轻量开源，无需地图平台 key |
| 测试 | pytest + mock LLM 集成测试 | 本地可跑、CI 友好 |

## 3. Agent 划分（6 个）

LangGraph supervisor 模式：主管识别意图并分派任务给 worker Agent，结果回流主管汇总。

| Agent | 职责 | 工具 |
|---|---|---|
| Supervisor 主管 | 意图识别（规划 / 攻略问答 / 修改请求），分派任务，汇总输出 | — |
| Analyst 需求分析师 | 追问补全出行信息，构建用户画像 | 会话记忆 |
| Planner 规划师 | 天级行程生成 + 修改后局部重排（吸收 Reviser：修订=带修改指令的重新规划） | 各 Agent 产出 |
| Researcher 研究员 | 景点/酒店/餐厅查询与推荐、实时天气（吸收 POI 搜索器与天气官） | `poi_search` / `weather` |
| Advisor 攻略顾问 | 知识型问答，规划时提供攻略增强（RAG 独立） | `rag_retrieve`（Chroma+BGE） |
| Budget 预算官 | 按预算上限分配住宿/交通/餐饮/门票，产出预算表 | 预算模型 |

### 协作流程示例

1. *"去东京有什么注意事项？"* → Supervisor 识别为知识问题 → Advisor 单独应答
2. *"10月去东京3天，预算8000，喜欢美食"* → Analyst 补全 → Researcher（天气+POI 并行 fan-out）→ Budget 分配 → Planner 生成 → Supervisor 汇总输出「行程 + 预算表 + 天气提示」
3. *"第二天换成博物馆"* → Planner 局部重排 → 增量更新行程

## 4. 工程结构

```
d:\agent\
├── backend/                      # Python + FastAPI + LangGraph
│   ├── app/
│   │   ├── agents/               # 6 个 agent 节点
│   │   ├── graph.py              # LangGraph StateGraph（节点/边/并行）
│   │   ├── state.py              # 共享状态模型（TypedDict）
│   │   ├── tools/                # weather_api.py / poi_db.py
│   │   ├── rag/                  # ingest.py / retriever.py / guides/
│   │   ├── llm/                  # DeepSeek Provider 层
│   │   ├── api/                  # 会话管理、SSE 流式端点
│   │   └── db.py                 # SQLite
│   └── tests/
├── frontend/                     # React + Vite + Tailwind + Leaflet
│   └── src/components/           # ChatPanel / ItineraryTimeline / MapView / BudgetTable / AgentProcessPanel
├── docs/
└── README.md
```

### 关键设计点

- **StateGraph + 共享状态**：节点通过 LangGraph 原生 TypedDict（`Annotated` reducer 字段）状态模型读写协作
- **checkpointer（SQLite）**：会话历史持久化，支撑多轮对话
- **并行 fan-out**：天气与 POI 查询并行执行
- **SSE 事件**：`agent_status`（谁在干活）/ `message`（对话）/ `itinerary_update`（增量行程）
- **前端主区域 Tab**：「行程时间线」/「地图视图」，POI 按天着色 + 路线连线 + 点击弹详情
- **RAG 数据自举**：DeepSeek 按模板生成城市攻略 → 切块 → BGE embedding → Chroma；人工抽查润色

## 5. 功能需求清单

1. 行程规划（天级：景点→餐厅→交通串联）
2. 预算管理（分配表）
3. 实时天气（影响行程：雨天排室内）
4. 个性化推荐 + 行程修改重排
5. POI 详情查询（时间线与地图双向联动）
6. RAG 攻略问答（知识问题 + 规划增强）
7. 地图可视化

## 6. 里程碑（M1→M6，每阶段可运行）

| 阶段 | 内容 | 完成标志 |
|---|---|---|
| M1 骨架 | 脚手架、FastAPI、LangGraph 空图、SSE 通道、SQLite | 前端收到测试推送 |
| M2 最小闭环 | Provider、Analyst+Planner、POI 库、天气适配器 | 简单行程可用 |
| M3 完整协作 | Supervisor 路由、Researcher/Budget、并行 | 完整产出 + 协作面板 |
| M4 对话能力 | checkpointer、修改→重排 | 增量更新行程 |
| M5 RAG 知识库 | ingest、Advisor、语义问答 | 攻略问题有据回答 |
| M6 地图与交付 | Leaflet、可视化完善、测试、文档、演示脚本 | 一键启动完整演示 |

## 7. 验证方式

- 每阶段：pytest 通过 + 手动对话演示
- M5：RAG 检索命中验证（回答内容源自知识库）
- M6：端到端演示脚本（规划→预算→改行程→攻略问答）
- 集成测试用 mock LLM，本地可跑

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| DeepSeek 长对话稳定性 | 结构化状态（JSON schema 产出），减少自由文本流转 |
| 天气 API 额度/访问 | 适配器抽象，失败降级模拟并标注 |
| BGE 模型体积 | bge-small-zh 轻量版，下载后缓存 |
| LangGraph 学习曲线 | M1 最小图先行验证，再逐节点扩展 |
