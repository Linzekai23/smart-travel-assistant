import { useEffect, useState } from "react";
import { CheckOutlined, LoadingOutlined } from "@ant-design/icons";
import { connectSse } from "../api/sse";

/** 后端多 Agent 协作流程（图节点顺序：analyst → researcher‖budget → planner → supervisor）。 */
const AGENT_FLOW: { key: string; label: string }[] = [
  { key: "analyst", label: "需求分析师" },
  { key: "researcher", label: "研究员" },
  { key: "budget", label: "预算官" },
  { key: "planner", label: "行程规划师" },
  { key: "supervisor", label: "主管" },
];

type AgentStatus = "pending" | "running" | "done";

/** 发送行程期间展示各 Agent 工作进度：订阅后端 /api/events 的 agent_status 事件。
 * 组件只在 sending 时挂载（key 随消息数变化），卸载即断开连接并丢弃状态。 */
export default function AgentWorkflow() {
  const [statuses, setStatuses] = useState<Record<string, AgentStatus>>({});

  useEffect(() => {
    return connectSse((event) => {
      if (event.type !== "agent_status") return;
      const idx = AGENT_FLOW.findIndex((a) => a.key === event.data.agent);
      if (idx < 0) return;
      setStatuses((prev) => {
        const next = { ...prev };
        if (event.data.status === "start") {
          // 更早的 Agent 若从未收到事件（挂载晚于其 start/done）→ 必已完成
          for (const a of AGENT_FLOW.slice(0, idx)) {
            if (!(a.key in next)) next[a.key] = "done";
          }
          next[AGENT_FLOW[idx].key] = "running";
        } else {
          next[AGENT_FLOW[idx].key] = "done";
        }
        return next;
      });
    });
  }, []);

  return (
    <ul className="mt-1.5 space-y-1">
      {AGENT_FLOW.map(({ key, label }) => {
        const st = statuses[key] ?? "pending";
        return (
          <li key={key} className="flex items-center gap-1.5 text-xs">
            {st === "done" ? (
              <CheckOutlined className="text-brand" />
            ) : st === "running" ? (
              <LoadingOutlined className="text-brand" />
            ) : (
              <span className="inline-block h-2.5 w-2.5 rounded-full border border-slate-300" />
            )}
            <span
              className={
                st === "pending"
                  ? "text-slate-300"
                  : st === "done"
                    ? "text-slate-500"
                    : "font-medium text-brand"
              }
            >
              {label}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
