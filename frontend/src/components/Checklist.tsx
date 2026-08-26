import { useEffect, useRef, useState } from "react";
import { Button, Card, Checkbox, Input, Progress } from "antd";
import { PlusOutlined } from "@ant-design/icons";

const DEFAULT_CATEGORIES: { category: string; items: string[] }[] = [
  { category: "证件", items: ["身份证", "护照", "驾照", "学生证"] },
  { category: "衣物", items: ["换洗衣物", "外套", "舒适的鞋", "雨伞/雨衣"] },
  { category: "数码", items: ["手机", "充电器", "充电宝", "耳机", "相机"] },
  { category: "药品", items: ["常用药", "创可贴", "晕车药", "驱蚊液"] },
  { category: "其他", items: ["水杯", "纸巾", "现金", "洗漱用品"] },
];

const STORAGE_KEY = "travel_checklist_state";

interface ChecklistState {
  checked: string[];
  custom: Record<string, string[]>;
}

function loadState(): ChecklistState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as ChecklistState;
      return {
        checked: Array.isArray(parsed.checked) ? parsed.checked : [],
        custom: parsed.custom && typeof parsed.custom === "object" ? parsed.custom : {},
      };
    }
  } catch {
    /* 损坏数据忽略，回到默认 */
  }
  return { checked: [], custom: {} };
}

export default function Checklist() {
  const [checked, setChecked] = useState<Set<string>>(() => new Set(loadState().checked));
  const [custom, setCustom] = useState<Record<string, string[]>>(() => loadState().custom);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const savedRef = useRef(false);

  // 勾选/自定义变化 → localStorage（首次渲染不写，避免覆盖旧数据）
  useEffect(() => {
    if (!savedRef.current) {
      savedRef.current = true;
      return;
    }
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ checked: [...checked], custom }),
    );
  }, [checked, custom]);

  const allItems = (category: string) => [
    ...DEFAULT_CATEGORIES.find((c) => c.category === category)!.items,
    ...(custom[category] ?? []),
  ];

  const addItem = (category: string) => {
    const name = (inputs[category] ?? "").trim();
    if (!name) return;
    setCustom((prev) => ({ ...prev, [category]: [...(prev[category] ?? []), name] }));
    setInputs((prev) => ({ ...prev, [category]: "" }));
  };

  const totalCount = DEFAULT_CATEGORIES.reduce(
    (n, c) => n + allItems(c.category).length,
    0,
  );
  const checkedCount = [...checked].length;

  return (
    <div className="mx-auto max-w-3xl p-4 md:p-6">
      <h2 className="mb-1 text-lg font-semibold text-slate-800">出行清单</h2>
      <p className="mb-4 text-sm text-slate-500">
        出行准备事项勾选清单，状态自动保存在本机浏览器
      </p>

      <Card size="small" className="mb-4">
        <div className="flex items-center gap-3">
          <Progress
            percent={totalCount ? Math.round((checkedCount / totalCount) * 100) : 0}
            className="flex-1"
          />
          <span className="shrink-0 text-sm text-slate-500">
            {checkedCount}/{totalCount} 已准备
          </span>
        </div>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        {DEFAULT_CATEGORIES.map(({ category }) => {
          const items = allItems(category);
          const checkedInCat = items.filter((i) => checked.has(`${category}:${i}`));
          return (
            <Card
              key={category}
              size="small"
              title={category}
              extra={
                <span className="text-xs text-slate-400">
                  {checkedInCat.length}/{items.length}
                </span>
              }
            >
              <Checkbox.Group
                className="flex flex-col gap-1.5"
                value={checkedInCat.map((i) => `${category}:${i}`)}
                onChange={(vals) => {
                  const key = (v: string) => `${category}:${v}`;
                  setChecked((prev) => {
                    const next = new Set(prev);
                    items.forEach((i) => next.delete(key(i)));
                    (vals as string[]).forEach((v) => next.add(v));
                    return next;
                  });
                }}
              >
                {items.map((i) => (
                  <Checkbox key={`${category}:${i}`} value={`${category}:${i}`}>
                    {i}
                  </Checkbox>
                ))}
              </Checkbox.Group>
              <div className="mt-3 flex gap-2">
                <Input
                  size="small"
                  placeholder="添加自定义项，回车确认"
                  value={inputs[category] ?? ""}
                  onChange={(e) =>
                    setInputs((prev) => ({ ...prev, [category]: e.target.value }))
                  }
                  onPressEnter={() => addItem(category)}
                />
                <Button
                  size="small"
                  icon={<PlusOutlined />}
                  onClick={() => addItem(category)}
                >
                  添加
                </Button>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
