import { useEffect, useRef, useState } from "react";
import ChatPanel, { type ChatMessage } from "./components/ChatPanel";
import EmptyState from "./components/EmptyState";
import TopBar from "./components/TopBar";
import TripView, { type Trip } from "./components/TripView";

const SESSION_KEY = "travel_session_id";

function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [trip, setTrip] = useState<Trip | null>(null);
  // session_id 持久化到 localStorage：刷新页面后恢复会话（历史消息 + 画像延续）
  const [sessionId, setSessionId] = useState<string | null>(
    () => localStorage.getItem(SESSION_KEY),
  );
  const [sending, setSending] = useState(false);
  // 请求纪元：handleReset 时 +1，过期请求的响应/错误一律丢弃，防止旧会话复活
  const epochRef = useRef(0);

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
    // 在途防重：请求未返回期间 trip 仍为 null，EmptyState 的"试试"按钮仍可点，
    // 二次点击会并发发出两个 /api/chat（双会话、双气泡）
    if (sending) return;
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setSending(true);
    const epoch = epochRef.current;
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
      // 响应返回前用户已点"新对话"：丢弃过期结果，不写 localStorage、不改 state、不追加消息
      if (epoch !== epochRef.current) return;
      localStorage.setItem(SESSION_KEY, data.session_id);
      setSessionId(data.session_id);
      setTrip(data.trip ?? null);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.reply },
      ]);
    } catch (err) {
      // 重置后到达的失败同样静默丢弃（旧请求不该再往新会话塞错误气泡）
      if (epoch !== epochRef.current) return;
      // 发送失败不保留旧 trip：否则错误消息成为最后一条 assistant 消息且 trip 非空，
      // 会被渲染成旧地图 TripView（stale 数据误导用户）
      setTrip(null);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: err instanceof Error ? err.message : String(err),
          error: true,
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  // 开启新对话：清除本地会话标识与全部状态，回到全新会话
  const handleReset = () => {
    epochRef.current += 1; // 使在途请求的后续处理失效
    localStorage.removeItem(SESSION_KEY);
    setSessionId(null);
    setMessages([]);
    setTrip(null);
  };

  return (
    <div className="flex h-dvh flex-col bg-slate-50">
      <TopBar hasSession={!!sessionId} onReset={handleReset} />
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <aside className="flex h-[45vh] w-full flex-col border-b border-slate-200 bg-white md:h-auto md:w-96 md:shrink-0 md:border-b-0 md:border-r">
          <ChatPanel messages={messages} sending={sending} onSend={handleSend} />
        </aside>
        <main className="min-w-0 flex-1 overflow-y-auto p-4 md:p-6">
          {trip ? (
            <TripView trip={trip} />
          ) : (
            <EmptyState onTry={handleSend} />
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
