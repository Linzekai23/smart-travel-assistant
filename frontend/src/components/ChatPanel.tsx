import { useState } from "react";

export default function ChatPanel() {
  const [text, setText] = useState("");
  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 p-4 overflow-y-auto">
        <p className="text-sm text-slate-500">输入出行需求，例如"10月去东京玩3天，预算8000，喜欢美食"</p>
      </div>
      <div className="p-3 border-t border-slate-200 flex gap-2">
        <input
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
          placeholder="输入出行需求…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white">
          发送
        </button>
      </div>
    </div>
  );
}
