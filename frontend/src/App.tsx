import { useEffect, useState } from "react";
import AgentProcessPanel from "./components/AgentProcessPanel";
import ChatPanel from "./components/ChatPanel";
import { connectSse, type ProcessEvent } from "./api/sse";

function App() {
  const [events, setEvents] = useState<ProcessEvent[]>([]);

  useEffect(() => {
    return connectSse((ev) => setEvents((prev) => [...prev, ev].slice(-50)));
  }, []);

  return (
    <div className="h-screen flex bg-slate-50">
      <div className="w-80 border-r border-slate-200 bg-white">
        <ChatPanel />
      </div>
      <main className="flex-1 p-6 overflow-y-auto">
        <h1 className="text-xl font-bold text-slate-800 mb-4">智能旅行助手</h1>
        <p className="text-sm text-slate-500">
          主区域：行程可视化（M6 实现）。当前显示实时 Agent 协作面板的连通状态。
        </p>
      </main>
      <AgentProcessPanel events={events} />
    </div>
  );
}

export default App;
