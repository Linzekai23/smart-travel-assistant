export interface PingEvent {
  type: "ping";
  data: { ts: number };
}

export interface AgentStatusEvent {
  type: "agent_status";
  data: { agent: string; status: "start" | "done"; detail?: string };
}

export interface ItineraryEvent {
  type: "itinerary_update";
  data: { itinerary: Record<string, unknown> };
}

export interface ErrorEvent {
  type: "error";
  data: { reason?: string };
}

export type ProcessEvent = PingEvent | AgentStatusEvent | ItineraryEvent | ErrorEvent;

/**
 * 后端帧统一为 {"type": T, "data": {...}}；所有事件类型共用该解析路径，
 * 解包 .data 字段后交给 onEvent。解析失败上报一次 error 事件。
 */
function handle<T>(
  type: ProcessEvent["type"],
  e: Event,
  onEvent: (event: ProcessEvent) => void
): void {
  try {
    const parsed = JSON.parse((e as MessageEvent).data) as { data: T };
    onEvent({ type, data: parsed.data } as ProcessEvent);
  } catch {
    onEvent({ type: "error", data: { reason: "parse" } });
  }
}

/** 连接后端 SSE 事件流，返回断开连接的函数。 */
export function connectSse(
  onEvent: (event: ProcessEvent) => void
): () => void {
  let connected = false;
  let reportedDown = false;
  const source = new EventSource("/api/events");
  source.addEventListener("ping", (e) =>
    handle<PingEvent["data"]>("ping", e, onEvent)
  );
  source.addEventListener("agent_status", (e) =>
    handle<AgentStatusEvent["data"]>("agent_status", e, onEvent)
  );
  source.addEventListener("itinerary_update", (e) =>
    handle<ItineraryEvent["data"]>("itinerary_update", e, onEvent)
  );
  source.onopen = () => {
    connected = true;
  };
  source.onerror = () => {
    // 首次 onerror（无论是否曾连上）上报一次错误：后端不可达时页面
    // 也能得到提示，而不是永远停留在"等待事件…"。
    if (connected) {
      connected = false;
      onEvent({ type: "error", data: {} });
    } else if (!reportedDown) {
      reportedDown = true;
      onEvent({ type: "error", data: {} });
    }
    // 其余情况：EventSource 自动重试期间的连续 onerror 不再重复推送。
  };
  return () => source.close();
}
