export interface ProcessEvent {
  type: string;
  data: Record<string, unknown>;
}

/** 连接后端 SSE 事件流，返回断开连接的函数。 */
export function connectSse(
  onEvent: (event: ProcessEvent) => void
): () => void {
  let connected = false;
  const source = new EventSource("/api/events");
  source.addEventListener("ping", (e) => {
    try {
      onEvent({ type: "ping", data: JSON.parse((e as MessageEvent).data) });
    } catch {
      onEvent({ type: "error", data: { reason: "parse" } });
    }
  });
  source.onopen = () => {
    connected = true;
  };
  source.onerror = () => {
    // 仅在连接状态发生转变（已连接 → 断开）时上报一次错误，
    // EventSource 自动重试期间的连续 onerror 不再重复推送。
    if (connected) {
      connected = false;
      onEvent({ type: "error", data: {} });
    }
  };
  return () => source.close();
}
