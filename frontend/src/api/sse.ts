export interface ProcessEvent {
  type: string;
  data: Record<string, unknown>;
}

/** 连接后端 SSE 事件流，返回断开连接的函数。 */
export function connectSse(
  onEvent: (event: ProcessEvent) => void
): () => void {
  const source = new EventSource("/api/events");
  source.addEventListener("ping", (e) => {
    onEvent({ type: "ping", data: JSON.parse((e as MessageEvent).data) });
  });
  source.onerror = () => {
    onEvent({ type: "error", data: {} });
  };
  return () => source.close();
}
