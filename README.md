# 智能旅行助手（多 Agent）

多 Agent 协作的智能旅行助手 Web 应用 —— 作品集项目。
用户以自然语言提出出行需求（**支持全国 34 个省级行政区的著名景点检索**），多个专业 Agent 协作完成
行程规划、天气查询与个性化推荐。

架构：**LangGraph supervisor 模式 + 5 个 Agent**（Supervisor / Analyst / Planner / Researcher / Budget），
FastAPI 后端 + React 前端，SSE 实时推送协作过程。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · LangGraph（含 langgraph-checkpoint-sqlite 会话持久化） · SQLite · httpx |
| LLM | DeepSeek（OpenAI 兼容，JSON 模式） |
| **RAG 知识库** | **Chroma + BGE（bge-small-zh-v1.5，ModelScope 下载）**，全国 34 省级行政区著名景点（省份-城市-景点三级粒度检索） |
| 前端 | React 19 · Vite 8 · TypeScript · Tailwind v4 |
| 实时通信 | SSE（ping / agent_status / itinerary_update 事件） |

## 目录结构

```
backend/   FastAPI + LangGraph（agents/ 节点 · rag/ 向量知识库 · tools/ 天气 · llm/ Provider · api/）
frontend/  React 三栏骨架（聊天 / 行程主区域 / Agent 协作面板）
docs/      设计文档与里程碑计划
scripts/    一键启动脚本（bash scripts/dev.sh）
```

## 快速开始

### 一键启动（推荐）

```bash
bash scripts/dev.sh           # 依赖与 RAG 库就绪时直接启动（后端 + 前端 + 打开浏览器）
bash scripts/dev.sh --setup   # 首次运行：自动下载 BGE 模型、生成 34 省语料、向量入库后启动
```

> 需先配置 `DEEPSEEK_API_KEY` 环境变量；脚本会自动检查后端/前端依赖与 RAG 库是否就绪。
> 架构与协作设计（mermaid 图）见 [docs/architecture.md](docs/architecture.md)。

### 1. 后端

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"     # 含 chromadb/transformers/torch 等 RAG 依赖
export DEEPSEEK_API_KEY=sk-xxx          # DeepSeek 平台申请；配置后聊天功能可用（Git Bash；cmd 用 set）
# 首次运行需准备 RAG 知识库（三步）：
.venv/Scripts/python -m app.rag.download_model   # 1. 下载 BGE 模型（ModelScope，约 95MB）
.venv/Scripts/python -m app.rag.generate        # 2. 生成 34 省 POI 语料（DeepSeek 约 34 次调用）
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
输入"广东"会检索全省著名景点；输入库外城市"佛山"，则 fallback 到广东省其他景点。
继续发送"第二天换成博物馆"，助手会保留目的地/天数/预算，重排出一份完整新行程；
刷新页面后历史对话自动恢复，可继续追问。

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
| M2 最小闭环（DeepSeek + **RAG POI 知识库** + Analyst/Planner + 天气） | ✅ 完成 |
| M3 完整协作（34 省景点库 + Supervisor 路由 + Researcher/Budget + 并行） | ✅ 完成 |
| M4 对话能力（会话持久化 + 修改重排） | ✅ 完成 |
| M5 地图与交付（Leaflet 地图 + 结构化日卡 + 文档 + 演示脚本） | ✅ 完成 |

详细设计见 [docs/superpowers/specs/2026-08-19-travel-assistant-design.md](docs/superpowers/specs/2026-08-19-travel-assistant-design.md)
