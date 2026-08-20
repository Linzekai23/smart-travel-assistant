import type { ProcessEvent } from "../api/sse";

const AGENT_NAMES: Record<string, string> = {
  analyst: "需求分析师",
  planner: "行程规划师",
  supervisor: "主管",
};

function describe(e: ProcessEvent): string | null {
  switch (e.type) {
    case "ping":
      return null; // 心跳不展示
    case "agent_status": {
      const name = AGENT_NAMES[e.data.agent] ?? e.data.agent;
      return e.data.status === "start"
        ? `${name} 开始工作${e.data.detail ? `：${e.data.detail}` : ""}…`
        : `${name} 完成`;
    }
    case "itinerary_update":
      return "行程已更新（将在主区域展示）";
    case "error":
      return e.data.reason === "parse" ? "事件解析失败" : "连接中断，正在重连…";
  }
}

interface Props {
  events: ProcessEvent[];
}

export default function AgentProcessPanel({ events }: Props) {
  const visible = events
    .map((e, i) => ({ e, i }))
    .filter(({ e }) => describe(e) !== null);

  return (
    <aside className="w-64 border-l border-slate-200 bg-white p-4 overflow-y-auto">
      <h2 className="text-sm font-semibold text-slate-600 mb-3">Agent 协作</h2>
      {visible.length === 0 && (
        <p className="text-xs text-slate-400">等待事件…</p>
      )}
      <ul className="space-y-1">
        {visible.map(({ e, i }) => (
          <li key={i} className="text-xs text-slate-500">
            {describe(e)}
          </li>
        ))}
      </ul>
    </aside>
  );
}
