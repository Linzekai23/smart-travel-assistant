import { useEffect, useRef, useState } from "react";
import { Avatar, Button, Input, Spin } from "antd";
import {
  EnvironmentOutlined,
  ExclamationCircleOutlined,
  RobotOutlined,
  SendOutlined,
} from "@ant-design/icons";
import { BRAND } from "../theme";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  error?: boolean;
}

interface Props {
  messages: ChatMessage[];
  sending: boolean;
  onSend: (text: string) => void;
}

export default function ChatPanel({ messages, sending, onSend }: Props) {
  const [text, setText] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  // 新消息/发送状态变化时自动滚动到底部
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, sending]);

  const submit = () => {
    const t = text.trim();
    if (!t || sending) return;
    onSend(t);
    setText("");
  };

  return (
    <div className="flex h-full flex-col">
      <div
        ref={listRef}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-4"
      >
        {messages.length === 0 && !sending ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <EnvironmentOutlined className="text-2xl text-brand/60" />
            <p className="text-sm font-medium text-slate-600">
              输入出行需求，生成你的专属行程
            </p>
            <p className="text-xs text-slate-400">
              例如"10月去成都玩3天，预算8000，喜欢美食"
            </p>
          </div>
        ) : (
          <>
            {messages.map((m, i) =>
              m.role === "user" ? (
                <div
                  key={i}
                  className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-brand px-3.5 py-2.5 text-sm text-white shadow-sm"
                >
                  {m.content}
                </div>
              ) : m.error ? (
                <div key={i} className="flex items-start gap-2">
                  <Avatar
                    size={28}
                    icon={<RobotOutlined />}
                    style={{ backgroundColor: BRAND }}
                  />
                  <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-sm border border-red-200 bg-red-50 px-3.5 py-2.5 text-sm text-red-700 shadow-sm">
                    <ExclamationCircleOutlined className="mr-1 text-red-500" />
                    {m.content}
                  </div>
                </div>
              ) : (
                <div key={i} className="flex items-start gap-2">
                  <Avatar
                    size={28}
                    icon={<RobotOutlined />}
                    style={{ backgroundColor: BRAND }}
                  />
                  <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 shadow-sm">
                    {m.content}
                  </div>
                </div>
              ),
            )}
            {sending && (
              <div className="flex items-start gap-2">
                <Avatar
                  size={28}
                  icon={<RobotOutlined />}
                  style={{ backgroundColor: BRAND }}
                />
                <div className="flex items-center gap-2 rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-3.5 py-2.5 shadow-sm">
                  <Spin size="small" />
                  <span className="text-xs text-slate-400">正在规划行程…</span>
                </div>
              </div>
            )}
          </>
        )}
      </div>
      <div className="border-t border-slate-200 p-3">
        <div className="flex items-end gap-2">
          <Input.TextArea
            autoSize={{ minRows: 1, maxRows: 4 }}
            maxLength={2000}
            placeholder="输入出行需求…"
            disabled={sending}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onPressEnter={(e) => {
              if (e.nativeEvent.isComposing) return; // 中文输入法组词回车不发送
              e.preventDefault();
              submit();
            }}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={sending}
            disabled={!text.trim()}
            onClick={submit}
          >
            发送
          </Button>
        </div>
      </div>
    </div>
  );
}
