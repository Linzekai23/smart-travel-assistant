import { Button } from "antd";
import { EnvironmentOutlined } from "@ant-design/icons";

interface Props {
  onTry?: (text: string) => void;
}

export default function EmptyState({ onTry }: Props) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
      <div className="flex h-20 w-20 items-center justify-center rounded-full bg-brand/10">
        <EnvironmentOutlined className="text-4xl text-brand" />
      </div>
      <div>
        <p className="text-lg font-semibold text-slate-800">还没有行程</p>
        <p className="mt-1 text-sm text-slate-500">
          在左侧输入你的旅行需求，助手会为你生成地图行程、每日安排与预算分配
        </p>
      </div>
      <Button
        type="primary"
        onClick={() => onTry?.("10月去成都玩3天，预算8000，喜欢美食")}
      >
        试试：10月去成都玩3天，预算8000，喜欢美食
      </Button>
    </div>
  );
}
