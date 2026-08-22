# 前端 UI 重设计（Ant Design + 两栏布局）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Ant Design v5 重构前端 UI：顶部栏 + 左聊天（真对话流）+ 主区域行程的两栏布局，清爽浅色 + 品牌色 teal，移除 Agent 协作面板。

**Architecture:** antd v5（CSS-in-JS，ConfigProvider token 主题）+ 现有 Tailwind v4 共存（外壳布局用 Tailwind flex，交互组件用 antd；绝不在 antd 组件上直接堆 Tailwind 间距/颜色类）。品牌色 `#0d9488` 单一来源 `src/theme.ts`，同步到 antd token / Tailwind @theme / Leaflet marker。

**Tech Stack:** React 19.2.8、antd ^5.29.3 + @ant-design/icons ^5.6.1 + @ant-design/v5-patch-for-react-19 ^1.0.3、Tailwind v4、react-leaflet 5（不改）。

**Spec:** （用户批准的 plan）C:\Users\林泽锴\.claude\plans\agent-concurrent-storm.md

## Global Constraints

- 后端 API 契约不变：`/api/chat` → {session_id, reply, trip}、`/api/itinerary?session_id=`、`/api/chat/history?session_id=`；后端代码零改动
- 免责声明文案逐字：`AI 生成示例数据，坐标仅供参考`，保留在地图上（z-[1000] 层级不变）
- 高德瓦片 TILE_URL / subdomains ["1","2","3","4"] / maxZoom 18 / attribution 逐字保留
- 前端新增依赖仅：antd@^5.29.3、@ant-design/icons@^5.6.1、@ant-design/v5-patch-for-react-19@^1.0.3
- 门禁：`npm run build`（tsc -b + vite build，0 错误；tsconfig 有 noUnusedLocals/verbatimModuleSyntax/erasableSyntaxOnly → 类型一律 `import type`、删引用必须彻底）+ `npm run lint`（oxlint）
- 品牌色：#0d9488（teal-600）；深色备选 #0f766e（teal-700）
- SSE 前端订阅移除（AgentProcessPanel + sse.ts 删除），后端 /api/events 保留（兼容）
- react-leaflet / leaflet 用法不变；Popup 内保持纯 HTML（不放 antd 组件）

---

### Task 1: UI 重设计（antd 组件化 + 两栏布局 + 去 Agent 面板）

**Files:**
- Modify: `frontend/package.json`（依赖）
- Create: `frontend/src/theme.ts`
- Modify: `frontend/src/index.css`（@theme 块）
- Modify: `frontend/src/main.tsx`（patch 首行 + ConfigProvider + AntApp + zhCN）
- Delete: `frontend/src/components/AgentProcessPanel.tsx`、`frontend/src/api/sse.ts`（及空 api/ 目录）
- Rewrite: `frontend/src/App.tsx`
- Create: `frontend/src/components/TopBar.tsx`、`frontend/src/components/EmptyState.tsx`
- Rewrite: `frontend/src/components/ChatPanel.tsx`（导出 `ChatMessage` 类型，App 引用）
- Rewrite: `frontend/src/components/TripView.tsx`（Props 与 `Trip`/`TripDay`/`TripItem` 导出不变）
- Modify: `frontend/src/components/ItineraryMap.tsx`（仅品牌色同步）

**Interfaces:**
- Consumes: 既有 `Trip`/`TripDay`/`TripItem`（TripView 导出）、`DayGeo`/`MapPoint`（ItineraryMap 导出）、`ChatMessage`（ChatPanel 导出）、`BRAND`/`themeConfig`（theme.ts 导出）
- Produces: `TopBar { hasSession: boolean; onReset: () => void }`；`EmptyState { onTry?: (text: string) => void }`；`ChatPanel { messages: ChatMessage[]; sending: boolean; onSend: (text: string) => void }`

- [ ] **Step 1: 安装依赖**

Run: `cd d:/agent/frontend && npm i antd@^5.29.3 @ant-design/icons@^5.6.1 @ant-design/v5-patch-for-react-19@^1.0.3`
Expected: 安装成功，无 peer 冲突（antd v5 peerDeps `react >= 16.9` 满足 React 19.2.8，无需 --legacy-peer-deps）

- [ ] **Step 2: 主题文件 theme.ts + index.css + main.tsx**

`src/theme.ts`（单一来源，与 index.css 的 --color-brand 保持一致）：
```ts
import type { ThemeConfig } from "antd";

/** 品牌色 —— 与 index.css 中 Tailwind @theme --color-brand 保持一致 */
export const BRAND = "#0d9488";

export const themeConfig: ThemeConfig = {
  token: {
    colorPrimary: BRAND,
    colorInfo: BRAND,
    colorLink: BRAND,
    borderRadius: 8,
    colorBgLayout: "#f2f7f6",
  },
};
```

`src/index.css`（追加 @theme 块，保留首行 `@import "tailwindcss";`）：
```css
@theme {
  /* 与 src/theme.ts 的 BRAND 保持一致 */
  --color-brand: #0d9488;
  --color-brand-strong: #0f766e;
}
```

`src/main.tsx`（patch 必须首行导入；ConfigProvider locale=zhCN + theme，AntApp 包裹提供 hook 版 message）：
```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import "@ant-design/v5-patch-for-react-19"; // 必须在任何 antd 组件渲染前导入
import "leaflet/dist/leaflet.css";
import "./index.css";
import App from "./App.tsx";
import { themeConfig } from "./theme";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConfigProvider locale={zhCN} theme={themeConfig}>
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </StrictMode>,
);
```

- [ ] **Step 3: 删除 AgentProcessPanel.tsx 与 sse.ts**（确认 App.tsx 是唯一引用者后删除；空 api/ 目录一并删）

- [ ] **Step 4: 重写 App.tsx**

- 移除：events state、connectSse import+effect、AgentProcessPanel、主区域消息渲染与 h1
- 保留：sessionId（localStorage `travel_session_id`）、trip、sending、挂载恢复 effect（history 含 `prev.length ? prev : data.messages` 竞态守卫 + itinerary 404→null）、handleSend
- handleSend 错误路径：消息加 `error: true` 标记（内容不再带 ⚠️ emoji）
- 新增 handleReset：removeItem + 清三个 state
- 外壳（h-dvh 替代 h-screen；滚动链每层 min-h-0）：

```tsx
<div className="flex h-dvh flex-col bg-slate-50">
  <TopBar hasSession={!!sessionId} onReset={handleReset} />
  <div className="flex min-h-0 flex-1 flex-col md:flex-row">
    <aside className="flex h-[45vh] w-full flex-col border-b border-slate-200 bg-white md:h-auto md:w-96 md:shrink-0 md:border-b-0 md:border-r">
      <ChatPanel messages={messages} sending={sending} onSend={handleSend} />
    </aside>
    <main className="min-w-0 flex-1 overflow-y-auto p-4 md:p-6">
      {trip ? <TripView trip={trip} reply={lastReply} /> : <EmptyState onTry={handleSend} />}
    </main>
  </div>
</div>
```

- `lastReply` = 最后一条 assistant 消息的 content（无则 `""`）；`ChatMessage` 类型从 ChatPanel 导入（含 error 可选字段）

- [ ] **Step 5: 新建 TopBar.tsx**

Props `{ hasSession: boolean; onReset: () => void }`：
- `<header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-2.5 md:px-6">`
- 左：`<EnvironmentOutlined className="text-xl text-brand" />` + `<h1 className="text-base font-semibold text-slate-800">智能旅行助手</h1>`
- 右：`hasSession ? <Tag icon={<CheckCircleOutlined />} color="success">会话进行中</Tag> : <Tag>新会话</Tag>`（外层 `hidden sm:block`）+ `<Button icon={<PlusOutlined />} onClick={resetAndToast}>新对话</Button>`
- resetAndToast：调 onReset() 后 `App.useApp().message.success("已开启新对话")`（从 antd 导入 `App as AntdApp` 使用 useApp）

- [ ] **Step 6: 新建 EmptyState.tsx**

Props `{ onTry?: (text: string) => void }`：
- 居中列：`h-20 w-20 rounded-full bg-brand/10 flex items-center justify-center` 圆底 + `<EnvironmentOutlined className="text-4xl text-brand" />`
- "还没有行程"（text-lg font-semibold）+ 引导文案（text-sm text-slate-500："在左侧输入你的旅行需求，助手会为你生成地图行程、每日安排与预算分配"）
- `<Button type="primary" onClick={() => onTry?.("10月去成都玩3天，预算8000，喜欢美食")}>试试：10月去成都玩3天，预算8000，喜欢美食</Button>`

- [ ] **Step 7: 重写 ChatPanel.tsx（真对话流）**

- 导出 `export interface ChatMessage { role: "user" | "assistant"; content: string; error?: boolean }`
- Props `{ messages: ChatMessage[]; sending: boolean; onSend: (text: string) => void }`
- 结构：`flex h-full flex-col` → 消息列表 `flex-1 min-h-0 overflow-y-auto px-3 py-4 space-y-3`（auto-scroll：`useRef` + `useEffect` 依赖 `[messages, sending]` 设 `scrollTop = scrollHeight`）→ 输入区 `border-t border-slate-200 p-3`
- 气泡：
  - 用户：`ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-brand px-3.5 py-2.5 text-sm text-white shadow-sm whitespace-pre-wrap`
  - 助手：`<Avatar size={28} icon={<RobotOutlined />} style={{ backgroundColor: BRAND }} />` + `max-w-[85%] rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 shadow-sm whitespace-pre-wrap`
  - error 消息：同助手但 `border-red-200 bg-red-50 text-red-700`，前加 `<ExclamationCircleOutlined className="mr-1 text-red-500" />`
  - 发送中（sending）：Avatar + 白气泡 `<Spin size="small" />` + `正在规划行程…`（text-xs text-slate-400）
  - 空态（无消息且非 sending）：居中 EnvironmentOutlined（text-2xl text-brand/60）+ "输入出行需求，生成你的专属行程" + 示例文案（text-xs text-slate-400）
- 输入：`<Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} maxLength={2000} placeholder="输入出行需求…" disabled={sending} />`
  - `onPressEnter={(e) => { if (e.nativeEvent.isComposing) return; e.preventDefault(); submit(); }}`（保留 IME 守卫；preventDefault 防换行）
  - 发送 `<Button type="primary" icon={<SendOutlined />} loading={sending} disabled={!text.trim()} onClick={submit}>发送</Button>`
  - 本地 text state + trim + 发送后清空逻辑保留

- [ ] **Step 8: 重写 TripView.tsx（antd 组件化）**

Props 与类型导出不变（Trip/TripDay/TripItem/`{ trip, reply }`）。改动：
- 日筛选 → antd `Tabs`：state `activeDay: string`（"all" | day 数字串）；items = `[{ key: "all", label: "全部" }, ...days.map(d => ({ key: String(d.day), label: `第${d.day}天` }))]`；传给 ItineraryMap 前转回 `const active: number | "all" = activeDay === "all" ? "all" : Number(activeDay)`
- 地图框保持纯 div：`h-[40vh] min-h-64 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm`（不包 Card，leaflet 需零 padding）
- 日卡 → `Card size="small"`（`styles={{ body: { paddingTop: 12 } }}` 可选微调），title=`第 {d.day} 天 · {d.title ?? ""}`，extra=天气 `<Tag icon={<CloudOutlined />}>{d.weather_note}</Tag>`
- 条目 → antd `Timeline`：每项 children = `<span className="font-mono text-xs text-slate-400">{it.time ?? "--:--"}</span> <span className="text-slate-800">{it.name}</span>` + note 时 `（{it.note}）`（text-xs text-slate-500）
- 预算 → `Card title="预算分配"` + antd `Table size="small" pagination={false} rowKey={(_, i) => i}`；columns：类别/说明/金额（align right，render `¥{amount}`，font-mono）；`footer={budget.total != null ? () => `合计 ¥${budget.total}` : undefined}`
- 总结 → `Card title="行程总结"`：summary 段落 + tips 列表每项 `<BulbOutlined className="mr-1 text-brand" />` 前缀
- 完整回复 → `Collapse ghost size="small"` 单项：label `查看完整文本回复`，children `<div className="whitespace-pre-wrap text-sm text-slate-700">{reply}</div>`；**仅 reply 非空时渲染**
- geoDays/visibleDays 计算逻辑不变

- [ ] **Step 9: ItineraryMap.tsx 品牌同步**

- `import { BRAND } from "../theme";`
- makeIcon html：`background:#2563eb` → `background:${BRAND}`（其余 iconSize/anchor/形状/白边/阴影不变）
- Polyline `pathOptions={{ color: BRAND, weight: 3, dashArray: "6 4" }}`
- Popup：🕐 emoji → `时间：{p.time}`；其余纯 HTML 不变
- 免责声明：文案与 z-[1000] 逐字保留（可微调 `bottom-1 left-1 rounded`）
- TILE_URL / subdomains / maxZoom / attribution / FitBounds 不动

- [ ] **Step 10: 门禁验证**

Run: `cd d:/agent/frontend && npm run build && npm run lint`
Expected: tsc -b 0 错误 + vite build 成功；oxlint 0 error（警告可接受）

- [ ] **Step 11: 提交**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src
git commit -m "feat: UI redesign — antd two-pane layout, real chat column, brand theme, drop agent panel

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 冒烟验证（controller 手动，Task 1 review 通过后）

dev.sh 运行中访问 http://localhost:5173：
1. 首载：TopBar"新会话"Tag、聊天空态提示、主区 EmptyState
2. 发送"10月去成都玩3天，预算8000，喜欢美食" → 用户 teal 右气泡 / Spin"正在规划行程…" / 助手回复气泡；主区 TripView：Tabs（全部/第1-3天）+ 地图 teal 编号标记 + teal 虚线 + 免责声明 + 日卡 Timeline + 预算 Table（合计 ¥8000）+ 总结 Card + Collapse
3. 点"第2天" → 地图只显示第 2 天点
4. "第二天换成博物馆" → replan 更新地图/日卡
5. 刷新 → 历史气泡 + 行程恢复，Tag"会话进行中"
6. "新对话" → 清空 + toast"已开启新对话"；停后端发送 → 红色错误气泡 + 主区 EmptyState
7. 窗口 < 768px → 堆叠布局（聊天上、行程下）
8. `git status` 无遗漏；免责声明逐字在页面上
