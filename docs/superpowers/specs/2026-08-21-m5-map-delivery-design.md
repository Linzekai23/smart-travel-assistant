# M5 地图与交付：Leaflet 地图 + 结构化日卡 + 一键演示

**日期：** 2026-08-21
**里程碑：** M5（地图与交付）——M4 已完成（会话持久化 + 修改重排，PR #4 已合并 8a446ef）
**前置：** PR #4 已合并，main 分支 HEAD 8a446ef

## 一、目标

作品集项目收官：行程从"纯文本 markdown"升级为**地图 + 结构化日卡**的可视化展示；一键脚本让演示零门槛；独立架构文档（mermaid 协作图）完整呈现多 Agent 技术方案。完成"规划→修改→重排→刷新恢复"的端到端交付演示。

## 二、决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 主区域改造 | **地图 + 结构化日卡**（替换原始 markdown） | 用户确认；演示效果完整 |
| 坐标数据链路 | **方案 A：后端富化 + 存库 + 新端点** | 一次往返拿到全部数据；刷新恢复完整；无 N+1 查询（vs checkpoint 直读脆弱 / 独立表过度设计） |
| 富化位置 | **planner 节点内**（产出后立即富化存回 state） | planner 本就消费 candidates，无需 chat.py 再跑一遍；SSE 事件可携带富化结果 |
| 地图瓦片 | **高德瓦片**（`webrd0{s}.is.autonavi.com` 无 key 模板，s=1-4） | 国内访问快、无 API key、中文样式（OSM/Carto 国内慢且不稳定） |
| GCJ-02 坐标转换 | **不做** | 语料坐标为 LLM 生成的近似值（"坐标仅供参考"免责声明覆盖），转换是形式主义；标记与瓦片的百米级偏移可接受 |
| 餐厅/酒店上地图 | **不上**（仅日卡展示） | 餐厅/酒店为 LLM 生成（示例）条目，语料中无坐标；景点才有 RAG 语料坐标 |
| 刷新恢复范围 | **地图+日卡随刷新恢复**（最新一条行程） | 用户确认；与 M4"刷新继续对话"体验一致 |
| 结构化行程存储 | **messages 表加 `trip_json TEXT NULL` 列** | 复用现有表；重排语义下仅最新行程有效（旧行程被整体覆盖），无需多版本 |
| 一键脚本 | **scripts/dev.sh 完整版**（依赖检查 + `--setup` 自动准备 + 双终端启动 + 开浏览器） | 用户确认；Git Bash 环境（项目 shell 事实标准） |
| 文档 | **docs/architecture.md**（mermaid ×3）+ README 链接 | 用户确认；面试作品集需独立深度的架构文档 |
| 新前端依赖 | leaflet + react-leaflet@5 + @types/leaflet | M5 里程碑核心（计划原文"Leaflet 地图"）；react-leaflet v5 兼容 React 19 |
| SSE 通道 | **激活 itinerary_update**（前后端已定义未使用） | 零成本增强：planner 完成即推送行程生成事件，Agent 面板可见 |

## 三、架构与组件改动

```
┌──────────────┐  POST /api/chat {message, session_id}
│   TripView   │ ────────────────────────────────────┐
│ 地图+日卡      │  GET /api/itinerary?session_id=    │
└──────────────┘                                    ▼
        │                                    ┌───────────────┐
        │ SSE agent_status/                  │   chat.py     │
        │ itinerary_update                   │  invoke 图 →   │
        ▼                                    │  result.trip   │
┌──────────────┐                             └───────┬───────┘
│ AgentPanel   │◄────────────────────────────────────┘
└──────────────┘                                      │
                                                      ▼
        planner: itinerary → enrich_itinerary(itinerary, candidates)
        （景点条目按 poi_id 附 lat/lng/name/category/reason）
                                                      │
                                                      ▼
        sqlite: data/travel.db
        ├─ messages 表新列 trip_json（assistant 消息附带）
        └─ langgraph checkpoint 表（现状不变）
```

### 后端

1. **新模块 `backend/app/itinerary.py`**：纯函数 `enrich_itinerary(itinerary: dict, candidates: list[dict]) -> dict`
   - 遍历 `itinerary["days"][].items[]`：条目有 `poi_id` 且命中 `candidates`（按 poi_id 匹配）→ 附加 `lat/lng/name/category/reason/description`（取候选值）；无 poi_id 或未命中 → 原样保留
   - 容忍 candidates 条目缺字段（测试 fake 场景）：字段存在才附加
   - 不动 itinerary 其他键（summary/warnings 原样透传）
2. **planner.py**：`planner_node` 产出 itinerary 后调用 `enrich_itinerary(itinerary, candidates)` 存回 state；随后 `events.publish({"type": "itinerary_update", "data": {"status": "generated", "itinerary": 富化行程}})`
3. **chat.py**：
   - 响应扩展：`{"session_id", "reply", "trip": {...} | null}`；`trip = {"itinerary": result["itinerary"], "budget_plan": result.get("budget_plan"), "summary": supervisor_summary.get("summary"), "tips": supervisor_summary.get("tips")}`；追问轮/降级（无行程）→ `trip: null`
   - assistant 落库时写 `trip_json`（`json.dumps(trip, ensure_ascii=False)`；trip 为 null 时写 NULL）
4. **db.py**：messages 表加 `trip_json TEXT NULL` 列；init_db 用 `PRAGMA table_info(messages)` 检查列是否存在，缺失则 `ALTER TABLE messages ADD COLUMN trip_json TEXT`（不破坏现有库）；新增 `get_latest_trip(session_id) -> dict | None`（最新一条非空 trip_json 反序列化）
5. **新端点 `GET /api/itinerary?session_id=`**：`get_latest_trip` 命中 → `{"session_id", "trip"}`；session 不存在或从未有行程 → 404（前端静默回退纯文本渲染）

### 前端

6. **新依赖**：`leaflet`、`react-leaflet@5`、`@types/leaflet`；main.tsx 引入 `leaflet/dist/leaflet.css`
7. **新组件 `components/ItineraryMap.tsx`**：
   - props：`days`（富化行程 days）、`activeDay`（number | "all"）、`onDayChange` 可选
   - MapContainer + TileLayer 高德瓦片模板 `https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}`（subdomains "1234"，maxZoom 18）
   - 标记：有 lat/lng 的景点条目 → 自定义 divIcon（圆形+编号，规避 bundler 下默认 marker 图标 404）；popup 显示 名称/时间/备注
   - 每日路线：当天 ≥2 个有坐标景点 → Polyline 按顺序连线
   - 过滤：activeDay 变化时仅显示当天标记/折线（"all" 全显）；fitBounds 至可见标记
   - 底部免责声明：`AI 生成示例数据，坐标仅供参考`
8. **新组件 `components/TripView.tsx`**：
   - props：`trip`（{itinerary, budget_plan, summary, tips}）、`reply`（对应文本回复）
   - 布局：顶部按天 tabs（第1天…第N天/全部）→ 地图（约 40% 高度）→ 日卡区 → 预算表卡片 → 总结/💡 tips 卡片；文本回复折叠（`<details>`）
   - 日卡：每天一张（标题、天气脚注 weather_note、条目时间线：时间/名称/note；（示例）标注原样保留）
9. **App.tsx**：
   - state 增 `trip: Trip | null`；发送成功 `setTrip(data.trip)`
   - 挂载恢复：history 恢复消息同时 `GET /api/itinerary` 恢复 trip（404/失败 → null，回退纯文本渲染——兼容 M4 前旧会话）
   - 渲染：最新一条 assistant 消息有 trip 时渲染 TripView（其余历史消息仍文本）；trip 为 null 时全部文本（现状行为）
10. **AgentProcessPanel.tsx**：`itinerary_update` 事件渲染为一条"行程已生成"状态行（若现组件未处理该类型——检查其事件分发逻辑，按既有 agent_status 渲染模式扩展）

### 数据流（端到端）

1. 用户"10月去成都玩3天…" → 图跑完 → planner 富化 itinerary（景点附坐标）→ state + SSE itinerary_update
2. chat.py 组装 trip（itinerary/budget_plan/summary/tips）→ 响应 + trip_json 落库
3. 前端 setTrip → TripView 渲染地图标记/日卡/预算卡片
4. "第二天换成博物馆" → 全图重跑 → 新 trip 覆盖 → 地图日卡更新
5. 刷新页面 → history 恢复消息 + /api/itinerary 恢复最新 trip → 地图日卡还原，继续对话

## 四、错误处理与边界

| 场景 | 行为 |
|---|---|
| 追问轮/降级回复（无 itinerary） | `trip: null`；前端回退纯文本渲染 |
| 景点 poi_id 未命中候选（幻觉已清洗，理论不出现） | 条目原样保留，不上地图 |
| 餐厅/酒店条目（无 poi_id） | 日卡正常展示，不上地图 |
| GET /api/itinerary：session 不存在/无行程 | 404；前端静默回退文本渲染 |
| 旧库（M4 前创建，无 trip_json 列） | init_db 自动 ALTER 迁移 |
| 高德瓦片加载失败（断网） | Leaflet 灰底 + 标记仍渲染；免责声明仍在 |
| 旧会话历史（trip_json 全空） | 404 → 文本渲染（向后兼容） |
| 刷新时 /api/itinerary 与 /api/chat/history 并发 | 两请求独立无依赖，各自静默降级 |

## 五、测试策略（全部 mock，无网络、无模型下载）

- `test_itinerary.py`（新）：enrich 单测——poi_id 命中附加坐标/未命中保留/无 poi_id 保留/空 candidates/候选缺字段容忍
- `test_chat.py` 扩展：响应含 trip（fake 候选带 lat/lng → 断言 trip.itinerary.days[0].items[0] 含 lat）；追问轮 trip 为 null；`GET /api/itinerary` 200（最新 trip）/ 404（不存在 session）/ 404（存在但无行程）
- `test_planner.py` 扩展：富化后 state itinerary 条目含坐标（fake candidates 带 lat/lng）；itinerary_update 事件发布——monkeypatch `app.agents.planner.events.publish` 断言调用参数（type=itinerary_update、data.status=generated）
- `test_db.py` 扩展：trip_json 列迁移（旧库 PRAGMA 无列 → init_db 后存在）；get_latest_trip 取最新非空
- 前端：`tsc -b` 0 errors + `vite build` 通过（项目既有门槛，无组件测试框架）

## 六、验收演示（controller 手动，最终审查前）

1. `bash scripts/dev.sh` 一键启动（依赖就绪场景；--setup 场景单独验证 RAG 三步可跑通）
2. 发送"10月去成都玩3天，预算8000，喜欢美食" → 地图显示景点标记（成都周边）、按天 tabs 过滤、日卡完整（天气/条目/（示例）标注）、预算表卡片、tips 卡片；Agent 面板可见 itinerary_update 事件
3. 发送"第二天换成博物馆" → 地图+日卡更新为新行程（画像延续）
4. 刷新页面 → 消息 + 地图日卡恢复 → 继续对话沿用画像
5. 结果记入 `.superpowers/sdd/progress.md`

## 七、范围外（YAGNI）

- GCJ-02/WGS-84 坐标转换
- 餐厅/酒店上地图（无数据源）
- 多行程历史版本（M4 已决策：全量重排整体覆盖）
- 离线地图/自托管瓦片
- react-router / 多页面
- 前端组件测试框架（vitest 等）——tsc+build 为项目既定门槛
- 地图聚合/聚类/搜索交互
- 移动端响应式适配
