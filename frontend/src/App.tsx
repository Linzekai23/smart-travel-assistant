import { useEffect, useState } from "react";
import AgentProcessPanel from "./components/AgentProcessPanel";
import ChatPanel from "./components/ChatPanel";
import { connectSse, type ProcessEvent } from "./api/sse";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

function App() {
  const [events, setEvents] = useState<ProcessEvent[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  // session_id 在页面会话内持续复用，使"Analyst 追问 → 用户补充回答"的
  // 多轮补全在同一会话内完成（刷新页面则开启新会话）。
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    return connectSse((ev) => setEvents((prev) => [...prev, ev].slice(-50)));
  }, []);

  const handleSend = async (text: string) => {
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setSending(true);
    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => null);
        throw new Error(err?.detail ?? `请求失败 (${resp.status})`);
      }
      const data = await resp.json();
      setSessionId(data.session_id);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.reply },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `⚠️ ${err instanceof Error ? err.message : String(err)}`,
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="h-screen flex bg-slate-50">
      <div className="w-80 border-r border-slate-200 bg-white flex flex-col">
        <ChatPanel onSend={handleSend} disabled={sending} />
      </div>
      <main className="flex-1 p-6 overflow-y-auto">
        <h1 className="text-xl font-bold text-slate-800 mb-4">智能旅行助手</h1>
        {messages.length === 0 ? (
          <p className="text-sm text-slate-500">
            输入出行需求，例如"10月去成都玩3天，预算8000，喜欢美食"。
            行程可视化与地图（M5）将在此区域展示。
          </p>
        ) : (
          <div className="space-y-4">
            {messages.map((m, i) => (
              <div
                key={i}
                className={
                  m.role === "user"
                    ? "text-sm text-slate-700 bg-white rounded-lg p-3 border border-slate-200 ml-16"
                    : "text-sm text-slate-800 bg-white rounded-lg p-4 border border-slate-200 whitespace-pre-wrap"
                }
              >
                {m.content}
              </div>
            ))}
            {sending && (
              <p className="text-xs text-slate-400">Agent 正在协作处理…</p>
            )}
          </div>
        )}
      </main>
      <AgentProcessPanel events={events} />
    </div>
  );
}

export default App;
