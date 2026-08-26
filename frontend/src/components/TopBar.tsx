import { App as AntdApp, Button, Menu, Tag } from "antd";
import {
  CheckCircleOutlined,
  EnvironmentOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import type { View } from "../views";

interface Props {
  view: View;
  onNavigate: (view: View) => void;
  hasSession: boolean;
  onReset: () => void;
}

/** 全局导航项（智能旅行助手放第一位） */
const NAV_ITEMS = [
  { key: "assistant", label: "智能旅行助手" },
  { key: "trips", label: "我的行程" },
  { key: "transport", label: "交通规划" },
  { key: "guide", label: "攻略浏览" },
  { key: "checklist", label: "出行清单" },
];

export default function TopBar({ view, onNavigate, hasSession, onReset }: Props) {
  const { message } = AntdApp.useApp();

  const resetAndToast = () => {
    onReset();
    message.success("已开启新对话");
  };

  return (
    <header className="flex items-center gap-4 border-b border-slate-200 bg-white px-4 py-2 md:px-6">
      <button
        type="button"
        onClick={() => onNavigate("home")}
        className="flex shrink-0 items-center gap-2"
        title="返回首页"
      >
        <EnvironmentOutlined className="text-xl text-brand" />
        <h1 className="text-base font-semibold text-slate-800">
          智能旅行系统
        </h1>
      </button>
      <Menu
        mode="horizontal"
        selectedKeys={view === "home" ? [] : [view]}
        items={NAV_ITEMS}
        onClick={({ key }) => onNavigate(key as View)}
        className="min-w-0 flex-1 border-b-0 !bg-transparent"
      />
      {view === "assistant" && (
        <div className="flex shrink-0 items-center gap-2">
          <span className="hidden sm:block">
            {hasSession ? (
              <Tag icon={<CheckCircleOutlined />} color="success">
                会话进行中
              </Tag>
            ) : (
              <Tag>新会话</Tag>
            )}
          </span>
          <Button icon={<PlusOutlined />} onClick={resetAndToast}>
            新对话
          </Button>
        </div>
      )}
    </header>
  );
}
