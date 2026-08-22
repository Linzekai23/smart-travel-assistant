# 智能旅行助手（多 Agent）设计文档

- 日期：2026-08-19（M3 设计修订：2026-08-20）
- 状态：已确认（与用户逐块评审通过）
- 定位：作品集项目 —— 展示多 Agent 协作、RAG、LLM 应用工程能力

## 1. 目标与背景

构建一个多 Agent 结构的智能旅行助手 Web 应用。用户以自然语言提出出行需求（**行程城市限国内（中国）**），系统通过多个专业 Agent 协作完成行程规划、预算分配、实时信息查询与个性化推荐。核心设计原则：**每个 Agent 职责单一、通过 LangGraph supervisor 模式协作、协作过程对用户可见**。

## 2. 设计决策

| 维度 | 决策 | 理由 |
|---|---|---|
| 产品形态 | Web 应用（React + Vite / FastAPI） | 作品集可演示性最强 |
| 编排框架 | LangGraph supervisor 模式 | 业界标准、自带状态管理与可视化、面试可迁移 |
| LLM | DeepSeek（OpenAI 兼容接口） | 国内直连、成本低、兼容性好 |
| 天气数据 | 真实天气 API 适配器 | 真实感；失败时降级模拟数据并标注 |
| POI 数据 | **RAG 知识库**（全国 34 省级行政区著名景点，省份-城市-景点三级粒度；LLM 自举生成语料 + BGE + Chroma） | 唯一数据源；语义检索；三级粒度检索（搜省→全省、搜库内城市→该市、搜库外城市→所在省）；语料标注"AI 生成示例数据" |
| 会话持久化 | SQLite + LangGraph checkpointer | 多轮对话与行程修改的基础 |
| 实时反馈 | SSE 流式推送 Agent 协作过程 | 演示最亮眼的部分 |
| 地图 | Leaflet + react-leaflet | 轻量开源，无需地图平台 key |
| 测试 | pytest + mock LLM 集成测试 | 本地可跑、CI 友好 |

## 3. Agent 划分（5 个）

LangGraph supervisor 模式：主管识别意图并分派任务给 worker Agent，结果回流主管汇总。

| Agent | 职责 | 工具 |
|---|---|---|
| Supervisor 主管 | 意图识别（规划 / 修改请求），分派任务，LLM 结构化汇总（summary/tips）后确定性格式化输出 | — |
| Analyst 需求分析师 | 追问补全出行信息，构建用户画像 | 会话记忆 |
| Planner 规划师 | 天级行程生成 + 修改后局部重排（吸收 Reviser：修订=带修改指令的重新规划） | `candidates`（景点候选+推荐要点）/ `budget_plan`（预算约束）；酒店/餐厅由 LLM 生成（标注"示例"） |
| Researcher 研究员 | 景点检索推荐（RAG 三级粒度语义检索：省 / 库内城市 / 库外城市→所在省）、实时天气 | `poi_search`（Chroma+BGE，province/city 过滤） / `weather` |
| Budget 预算官 | 按预算上限分配类别额度（住宿/交通/餐饮/门票/其他），产出预算表 | 预算模型（LLM 分配 + 确定性缩放兜底） |

### 协作流程示例

1. *"10月去成都玩3天，预算8000，喜欢美食"* → Analyst 补全 → **‖ Researcher（RAG 三级粒度检索景点 + 天气）‖ Budget（类别额度分配）‖ 并行** → Planner（预算约束下选景点排行程；酒店/餐厅 LLM 生成标注"示例"）→ Supervisor 汇总输出「行程 + 预算表 + 天气提示」
2. *"第二天换成博物馆"* → Planner 局部重排 → 增量更新行程

## 4. 工程结构

```
d:\agent\
├── backend/                      # Python + FastAPI + LangGraph
│   ├── app/
│   │   ├── agents/               # 5 个 agent 节点
│   │   ├── graph.py              # LangGraph StateGraph（节点/边/并行）
│   │   ├── state.py              # 共享状态模型（TypedDict）
│   │   ├── tools/                # weather_api.py（天气适配器）
│   │   ├── rag/                  # embeddings / vector_store / retriever / ingest / generate / province_cities
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
- **并行 fan-out**：Researcher（景点检索 + 天气）与 Budget（类别额度分配）并行执行，汇入 Planner
- **三级粒度检索**：用户搜省→全省景点；搜库内城市→该市景点；搜库外城市→`province_cities` 城市-省份映射表定位所在省 → 全省景点
- **酒店/餐厅**：不入库；Planner 规划时由 LLM 生成（标注"示例"），无 poi_id/坐标
- **SSE 事件**：`agent_status`（谁在干活）/ `message`（对话）/ `itinerary_update`（增量行程）
- **前端主区域 Tab**：「行程时间线」/「地图视图」，POI 按天着色 + 路线连线 + 点击弹详情
- **RAG POI 语料自举**：DeepSeek 按省份模板批量生成著名景点条目（34 省级行政区 × 每省模板预置 2-4 个著名旅游城市 × 1-3 景点 ≈ 170-200 条）→ 校验 → BGE embedding → Chroma 入库；人工抽查润色；**"周边"= 同城/同省其他景点 + 经纬度距离排序**；语料标注"AI 生成示例数据，坐标仅供参考"
- **旧 20 城语料删除替换**：M3 执行时删除旧 20 城语料（`backend/data/poi_corpus.jsonl`）与 Chroma 向量库，重新生成 34 省语料并重建入库，不保留旧条目

## 5. 功能需求清单

1. 行程规划（天级：景点→餐厅→交通串联）
2. 预算管理（分配表）
3. 实时天气（影响行程：雨天排室内）
4. 个性化推荐 + 行程修改重排
5. POI 详情查询与**周边推荐**（同城/同省其他景点按距离排序；时间线与地图双向联动）
6. 地图可视化

## 6. 里程碑（M1→M5，每阶段可运行）

| 阶段 | 内容 | 完成标志 |
|---|---|---|
| M1 骨架 | 脚手架、FastAPI、LangGraph 空图、SSE 通道、SQLite | 前端收到测试推送 |
| M2 最小闭环 | Provider、**RAG POI 知识库（初版 20 城，M3 删除替换）**、Analyst+Planner、天气适配器 | 国内城市简单行程可用，RAG 检索命中 |
| M3 完整协作 | **RAG 重构（34 省著名景点库 + 三级粒度检索）**、Supervisor 路由、Researcher/Budget、并行 fan-out | 完整产出「行程+预算表+天气」+ 5 Agent 协作面板 + 三级检索命中 |
| M4 对话能力 | checkpointer、修改→重排 | 增量更新行程 |
| M5 地图与交付 | Leaflet、可视化完善、测试、文档、演示脚本 | 一键启动完整演示 |

## 7. 验证方式

- 每阶段：pytest 通过 + 手动对话演示
- M3：RAG 语料静态断言（34 省全覆盖、每省 ≥ 3 景点、坐标在城市中心 ±2°）+ 三级粒度检索用例（搜省 / 搜库内城市 / 搜库外城市→所在省）
- M5：端到端演示脚本（规划→预算→改行程）
- 集成测试用 mock LLM + FakeEmbedder（无网络、无模型下载），本地可跑

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| DeepSeek 长对话稳定性 | 结构化状态（JSON schema 产出），减少自由文本流转 |
| 天气 API 额度/访问 | 适配器抽象，失败降级模拟并标注 |
| BGE 模型体积与下载 | bge-small-zh-v1.5 轻量版（约 95MB）；**huggingface 不可达 → 从 ModelScope 下载**（`snapshot_download`），下载后本地缓存离线加载 |
| LLM 生成语料坐标/评分误差 | 语料标注"AI 生成示例数据"；ingest 校验坐标在城市中心 ±2° 范围内，越界丢弃 |
| LangGraph 学习曲线 | M1 最小图先行验证，再逐节点扩展 |
