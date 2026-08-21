import { App as AntdApp, Button, Tag } from "antd";
import {
  CheckCircleOutlined,
  EnvironmentOutlined,
  PlusOutlined,
} from "@ant-design/icons";

interface Props {
  hasSession: boolean;
  onReset: () => void;
}

export default function TopBar({ hasSession, onReset }: Props) {
  const { message } = AntdApp.useApp();

  const resetAndToast = () => {
    onReset();
    message.success("已开启新对话");
  };

  return (
    <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-2.5 md:px-6">
      <div className="flex items-center gap-2">
        <EnvironmentOutlined className="text-xl text-brand" />
        <h1 className="text-base font-semibold text-slate-800">智能旅行助手</h1>
      </div>
      <div className="flex items-center gap-2">
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
    </header>
  );
}
