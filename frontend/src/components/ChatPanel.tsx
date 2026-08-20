import { useState } from "react";

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
}

export default function ChatPanel({ onSend, disabled }: Props) {
  const [text, setText] = useState("");

  const submit = () => {
    const t = text.trim();
    if (!t || disabled) return;
    onSend(t);
    setText("");
  };

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b border-slate-200">
        <p className="text-sm text-slate-500">
          输入出行需求，例如"10月去成都玩3天，预算8000，喜欢美食"
        </p>
      </div>
      <div className="p-3 border-t border-slate-200 flex gap-2 mt-auto">
        <input
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
          placeholder="输入出行需求…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing || e.key !== "Enter") return;
            submit();
          }}
        />
        <button
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50"
          disabled={disabled}
          onClick={submit}
        >
          发送
        </button>
      </div>
    </div>
  );
}
