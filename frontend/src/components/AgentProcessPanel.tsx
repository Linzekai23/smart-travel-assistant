export interface ProcessEvent {
  type: string;
  data: Record<string, unknown>;
}

interface Props {
  events: ProcessEvent[];
}

export default function AgentProcessPanel({ events }: Props) {
  return (
    <aside className="w-64 border-l border-slate-200 bg-white p-4 overflow-y-auto">
      <h2 className="text-sm font-semibold text-slate-600 mb-3">Agent 协作</h2>
      {events.length === 0 && (
        <p className="text-xs text-slate-400">等待事件…</p>
      )}
      <ul className="space-y-1">
        {events.map((ev, i) => (
          <li key={i} className="text-xs text-slate-500 font-mono">
            {ev.type === "ping"
              ? `已连接 (t=${String(ev.data.ts)})`
              : `${ev.type}: ${JSON.stringify(ev.data)}`}
          </li>
        ))}
      </ul>
    </aside>
  );
}
