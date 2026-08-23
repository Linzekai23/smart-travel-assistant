# 智能旅行助手（多 Agent）

多 Agent 协作的智能旅行助手 Web 应用 —— 作品集项目。
用户以自然语言提出出行需求（**支持全国 34 个省级行政区的著名景点检索**），多个专业 Agent 协作完成
行程规划、天气查询、预算分配与个性化推荐，并接入**高德真实餐厅/酒店数据**（地址、照片、地图打点）。

架构：**LangGraph supervisor 模式 + 5 个 Agent**（Analyst / Researcher / Budget / Planner / Supervisor），
FastAPI 后端 + React 前端，SSE 实时推送协作过程。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · LangGraph（含 langgraph-checkpoint-sqlite 会话持久化） · SQLite · httpx · Pillow（酒店照片择优评分） |
| LLM | DeepSeek（OpenAI 兼容，JSON 模式） |
| **RAG 知识库** | **Chroma + BGE（bge-small-zh-v1.5，ModelScope 下载）**，全国 34 省级行政区著名景点（省份-城市-景点三级粒度检索） |
| 前端 | React 19 · Vite · TypeScript · Tailwind v4 · **Ant Design v5** · Leaflet / react-leaflet |
| 实时通信 | SSE（ping / agent_status / itinerary_update 事件） |

## 目录结构

```
backend/   FastAPI + LangGraph（agents/ 5 个 Agent · rag/ 向量知识库 · tools/ 天气 · llm/ Provider · api/）
frontend/  React 两栏布局（顶部栏 + 左对话 + 右行程；components/ 含地图/图片/工作流组件）
docs/      架构文档与各里程碑设计文档
scripts/   一键启动脚本（bash scripts/dev.sh）
```

## 功能清单

- **多 Agent 协作规划**：Analyst（需求分析）→ Researcher‖Budget（区域检索 + 预算分配，并行）→ Planner（行程规划）→ Supervisor（汇总建议）；发送期间对话框下方实时展示各 Agent 工作进度（SSE）
- **自然语言行程**：目的地 / 天数 / 预算 / 偏好 → 逐日行程（时段建议、详细介绍、天气提示）；对话式修改重排（"第二天换成博物馆"）与刷新后会话恢复
- **全国 34 省景点检索**：RAG（Chroma + BGE）省份-城市-景点三级粒度；库外城市自动 fallback 到所在省
- **高德真实餐厅/酒店**：地址/照片进行程与地图（三色打点：景点=品牌色、餐厅=橙、酒店=蓝）；酒店多张照片按"阳光指数"自动择优（太暗时兜底城市酒店大堂美图）；同一商家全程只出现一次；**无高德 key 时自动降级为示例数据**
- **地图交互**：Leaflet + 高德瓦片；按天筛选；**点击景点/餐厅/酒店条目 → 视口滚到地图 + 飞行定位 + 弹出详情气泡**
- **行程面板**：结构化日卡（Timeline）、预算分配表（说明含估算依据 + 占比列）、详细行程总结 + 警示 + tips（自动去重）
- **精简对话栏**：回复每条一行，详细介绍/预算/总结都在右侧面板；错误红色气泡提示

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
export AMAP_KEY=xxx                     # 高德开放平台 Web 服务 key，可选；缺失时餐厅/酒店为示例数据
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

浏览器打开 http://localhost:5173，输入"10月去成都玩3天，预算8000，喜欢美食"：
发送期间对话框下方实时点亮各 Agent 工作流程；行程生成后右侧展示地图、日卡、预算与总结。
点击任意景点/餐厅/酒店条目，地图自动飞行定位并弹出详情；按天 Tab 筛选地图打点。
输入"广东"会检索全省著名景点；库外城市（如"佛山"）fallback 到广东省其他景点。
继续发送"第二天换成博物馆"，助手保留上下文重排行程；刷新页面后历史对话自动恢复。

> 语料为 **AI 生成示例数据，坐标仅供参考**；餐厅/酒店数据来自高德地图，营业信息可能变动。
> 如某城景点数据不理想，可编辑 `backend/data/poi_corpus.jsonl` 后重跑 `python -m app.rag.ingest` 增量入库。

## 测试

```bash
cd backend && .venv/Scripts/python -m pytest -q   # 184 tests 全部 mock（FakeProvider/FakeEmbedder），无需 API Key、无需模型、无网络
cd frontend && npm run build && npm run lint      # 前端门禁：tsc + vite 构建 + oxlint
```

## 里程碑

| 阶段 | 状态 |
|---|---|
| M1 骨架（FastAPI + SSE + SQLite + 图 + 前端骨架） | ✅ 完成 |
| M2 最小闭环（DeepSeek + **RAG POI 知识库** + Analyst/Planner + 天气） | ✅ 完成 |
| M3 完整协作（34 省景点库 + Supervisor 路由 + Researcher/Budget + 并行） | ✅ 完成 |
| M4 对话能力（会话持久化 + 修改重排） | ✅ 完成 |
| M5 地图与交付（Leaflet 地图 + 结构化日卡 + 文档 + 演示脚本） | ✅ 完成 |
| 高德真实餐厅/酒店接入（POI 检索 + enrich + 照片择优 + 地图打点） | ✅ 完成 |
| UI 重设计（Ant Design 两栏布局 + 地图交互 + 对话栏 Agent 工作流） | ✅ 完成 |

详细设计见 [docs/superpowers/specs/](docs/superpowers/specs/)（整体设计 / M4 对话 / M5 地图 / 高德真实商家接入）。
