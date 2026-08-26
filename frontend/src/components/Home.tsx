import type { ReactNode } from "react";
import {
  RobotOutlined,
  BookOutlined,
  CarOutlined,
  CompassOutlined,
  CheckSquareOutlined,
} from "@ant-design/icons";
import type { View } from "../views";

interface Feature {
  view: View;
  title: string;
  desc: string;
  icon: ReactNode;
}

/** 辅助功能小卡（助手大卡单独渲染） */
const FEATURES: Feature[] = [
  {
    view: "trips",
    title: "我的行程",
    desc: "保存与查看已生成的行程",
    icon: <BookOutlined className="text-2xl text-brand" />,
  },
  {
    view: "transport",
    title: "交通规划",
    desc: "查询地点间的交通方式与耗时",
    icon: <CarOutlined className="text-2xl text-brand" />,
  },
  {
    view: "guide",
    title: "攻略浏览",
    desc: "按城市浏览景点、美食与住宿",
    icon: <CompassOutlined className="text-2xl text-brand" />,
  },
  {
    view: "checklist",
    title: "出行清单",
    desc: "出行准备事项勾选清单",
    icon: <CheckSquareOutlined className="text-2xl text-brand" />,
  },
];

interface Props {
  onNavigate: (view: View) => void;
}

export default function Home({ onNavigate }: Props) {
  return (
    <div className="mx-auto flex min-h-full max-w-4xl flex-col justify-center gap-6 px-4 py-10 md:py-16">
      {/* 主功能 C 位大卡：智能旅行助手 */}
      <button
        type="button"
        onClick={() => onNavigate("assistant")}
        className="group flex items-center gap-5 rounded-2xl border border-brand/20 bg-gradient-to-br from-brand to-brand-strong p-6 text-left shadow-sm transition hover:shadow-lg md:p-8"
      >
        <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-white/15 text-3xl text-white">
          <RobotOutlined />
        </span>
        <span className="min-w-0">
          <span className="block text-xl font-bold text-white md:text-2xl">
            智能旅行助手
          </span>
          <span className="mt-1 block text-sm text-white/85 md:text-base">
            和 AI 对话，生成你的专属旅行行程 —— 主功能
          </span>
        </span>
        <span className="ml-auto hidden text-white/60 transition group-hover:translate-x-1 md:block">
          →
        </span>
      </button>

      {/* 辅助功能小卡 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {FEATURES.map((f) => (
          <button
            key={f.view}
            type="button"
            onClick={() => onNavigate(f.view)}
            className="flex items-center gap-4 rounded-xl border border-slate-200 bg-white p-5 text-left shadow-sm transition hover:border-brand/40 hover:shadow"
          >
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand/10">
              {f.icon}
            </span>
            <span className="min-w-0">
              <span className="block font-semibold text-slate-800">
                {f.title}
              </span>
              <span className="mt-0.5 block truncate text-sm text-slate-500">
                {f.desc}
              </span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
