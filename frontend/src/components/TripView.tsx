import { useMemo, useState } from "react";
import { Card, Collapse, Table, Tabs, Tag, Timeline } from "antd";
import type { TableProps } from "antd";
import { BulbOutlined, CloudOutlined } from "@ant-design/icons";
import ItineraryMap, { type DayGeo } from "./ItineraryMap";

export interface TripItem {
  time?: string;
  name: string;
  note?: string;
  poi_id?: string;
  lat?: number;
  lng?: number;
  category?: string;
}

export interface TripDay {
  day: number;
  title?: string;
  weather_note?: string;
  items: TripItem[];
}

export interface Trip {
  itinerary: { days: TripDay[]; summary?: string; warnings?: string[] };
  budget_plan: {
    items?: { category: string; amount: number; note?: string }[];
    total?: number | null;
  };
  summary?: string;
  tips?: string[];
}

interface BudgetRow {
  category: string;
  amount: number;
  note?: string;
}

const budgetColumns: TableProps<BudgetRow>["columns"] = [
  { title: "类别", dataIndex: "category" },
  { title: "说明", dataIndex: "note" },
  {
    title: "金额",
    dataIndex: "amount",
    align: "right",
    render: (v: number) => <span className="font-mono">¥{v}</span>,
  },
];

interface Props {
  trip: Trip;
  reply: string;
}

export default function TripView({ trip, reply }: Props) {
  const days = trip.itinerary.days ?? [];
  const [activeDay, setActiveDay] = useState<string>("all");

  // 只有带坐标的景点条目上地图（餐厅/酒店为（示例）条目，语料无坐标）
  const geoDays: DayGeo[] = useMemo(
    () =>
      days.map((d) => ({
        day: d.day,
        title: d.title,
        points: (d.items ?? [])
          .filter(
            (it): it is TripItem & { lat: number; lng: number } =>
              typeof it.lat === "number" && typeof it.lng === "number",
          )
          .map((it) => ({
            name: it.name,
            lat: it.lat,
            lng: it.lng,
            time: it.time,
            note: it.note,
          })),
      })),
    [days],
  );

  const budget = trip.budget_plan ?? {};
  const active: number | "all" =
    activeDay === "all" ? "all" : Number(activeDay);
  const visibleDays =
    active === "all" ? days : days.filter((d) => d.day === active);

  const tabItems = [
    { key: "all", label: "全部" },
    ...days.map((d) => ({ key: String(d.day), label: `第${d.day}天` })),
  ];

  return (
    <div className="space-y-4">
      {/* 按天过滤 tabs */}
      <Tabs activeKey={activeDay} onChange={setActiveDay} items={tabItems} />

      {/* 地图：保持纯 div 容器（leaflet 需要零内边距，不包 Card） */}
      <div className="h-[40vh] min-h-64 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <ItineraryMap days={geoDays} activeDay={active} />
      </div>

      {/* 日卡 */}
      {visibleDays.map((d) => (
        <Card
          key={d.day}
          size="small"
          title={`第 ${d.day} 天 · ${d.title ?? ""}`}
          extra={
            d.weather_note ? (
              <Tag icon={<CloudOutlined />}>{d.weather_note}</Tag>
            ) : undefined
          }
          styles={{ body: { paddingTop: 12 } }}
        >
          <Timeline
            items={(d.items ?? []).map((it) => ({
              children: (
                <>
                  <span className="font-mono text-xs text-slate-400">
                    {it.time ?? "--:--"}
                  </span>{" "}
                  <span className="text-slate-800">{it.name}</span>
                  {it.note && (
                    <span className="text-xs text-slate-500">（{it.note}）</span>
                  )}
                </>
              ),
            }))}
          />
        </Card>
      ))}

      {/* 预算卡片 */}
      {budget.items?.length ? (
        <Card title="预算分配">
          <Table<BudgetRow>
            size="small"
            pagination={false}
            rowKey={(_, i) => i!}
            columns={budgetColumns}
            dataSource={budget.items.map((it, i) => ({ key: i, ...it }))}
            footer={
              budget.total != null
                ? () => `合计 ¥${budget.total}`
                : undefined
            }
          />
        </Card>
      ) : null}

      {/* 总结 + tips */}
      {trip.summary || trip.tips?.length ? (
        <Card title="行程总结">
          {trip.summary && (
            <p className="text-sm text-slate-800">{trip.summary}</p>
          )}
          {trip.tips?.length ? (
            <ul className="mt-2 space-y-1 text-sm">
              {trip.tips.map((t, i) => (
                <li key={i} className="text-slate-600">
                  <BulbOutlined className="mr-1 text-brand" />
                  {t}
                </li>
              ))}
            </ul>
          ) : null}
        </Card>
      ) : null}

      {/* 完整文本回复折叠（仅回复非空时渲染） */}
      {reply ? (
        <Collapse
          ghost
          size="small"
          items={[
            {
              key: "reply",
              label: "查看完整文本回复",
              children: (
                <div className="whitespace-pre-wrap text-sm text-slate-700">
                  {reply}
                </div>
              ),
            },
          ]}
        />
      ) : null}
    </div>
  );
}
