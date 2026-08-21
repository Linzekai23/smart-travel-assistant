import { useEffect, useState } from "react";
import AgentProcessPanel from "./components/AgentProcessPanel";
import ChatPanel from "./components/ChatPanel";
import TripView, { type Trip } from "./components/TripView";
import { connectSse, type ProcessEvent } from "./api/sse";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

const SESSION_KEY = "travel_session_id";

function App() {
  const [events, setEvents] = useState<ProcessEvent[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [trip, setTrip] = useState<Trip | null>(null);
  // session_id 持久化到 localStorage：刷新页面后恢复会话（历史消息 + 画像延续）
  const [sessionId, setSessionId] = useState<string | null>(
    () => localStorage.getItem(SESSION_KEY),
  );
  const [sending, setSending] = useState(false);

  useEffect(() => {
    return connectSse((ev) => setEvents((prev) => [...prev, ev].slice(-50)));
  }, []);

  // 刷新后恢复历史消息与最新行程；失败（后端未启动/会话过期）静默降级为空会话
  useEffect(() => {
    const sid = localStorage.getItem(SESSION_KEY);
    if (!sid) return;
    fetch(`/api/chat/history?session_id=${encodeURIComponent(sid)}`)
      .then((resp) => (resp.ok ? resp.json() : null))
      .then((data) => {
        // 挂载竞态防护：history 返回前用户已极速首发消息（本地已入 state），
        // 此时只补历史、不整组覆盖（否则首条用户消息被历史数据冲掉）
        if (data?.messages?.length) {
          setMessages((prev) => (prev.length ? prev : data.messages));
        }
      })
      .catch(() => {});
    // 地图/日卡恢复：取最新一条结构化行程；无行程（404）→ 保持纯文本渲染
    fetch(`/api/itinerary?session_id=${encodeURIComponent(sid)}`)
      .then((resp) => (resp.ok ? resp.json() : null))
      .then((data) => {
        if (data?.trip) setTrip(data.trip);
      })
      .catch(() => {});
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
      localStorage.setItem(SESSION_KEY, data.session_id);
      setSessionId(data.session_id);
      setTrip(data.trip ?? null);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.reply },
      ]);
    } catch (err) {
      // 发送失败不保留旧 trip：否则错误消息成为 lastAssistantIdx 且 trip 非空，
      // 会被渲染成旧地图 TripView（stale 数据误导用户）
      setTrip(null);
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

  // 最新一条 assistant 消息且有结构化行程 → TripView；其余历史消息仍文本
  const lastAssistantIdx = messages.map((m) => m.role).lastIndexOf("assistant");

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
            生成的行程将以地图与日卡展示。
          </p>
        ) : (
          <div className="space-y-4">
            {messages.map((m, i) =>
              m.role === "user" ? (
                <div
                  key={i}
                  className="text-sm text-slate-700 bg-white rounded-lg p-3 border border-slate-200 ml-16"
                >
                  {m.content}
                </div>
              ) : i === lastAssistantIdx && trip ? (
                <TripView key={i} trip={trip} reply={m.content} />
              ) : (
                <div
                  key={i}
                  className="text-sm text-slate-800 bg-white rounded-lg p-4 border border-slate-200 whitespace-pre-wrap"
                >
                  {m.content}
                </div>
              ),
            )}
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
