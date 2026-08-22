import { useMemo, useState } from "react";
import { Card, Table, Tabs, Tag, Timeline } from "antd";
import type { TableProps } from "antd";
import {
  BulbOutlined,
  ClockCircleOutlined,
  CloudOutlined,
  HomeOutlined,
} from "@ant-design/icons";
import AttractionImage from "./AttractionImage";
import ItineraryMap, { type DayGeo } from "./ItineraryMap";

export interface TripItem {
  name: string;
  note?: string;
  // 详细介绍：景点 80-120 字（历史/看点），餐厅推荐美食，住宿环境
  detail?: string;
  // 景点专属：建议到访时段 + 为什么建议该时段（餐厅/酒店无）
  suggested_time?: string;
  time_reason?: string;
  poi_id?: string;
  lat?: number;
  lng?: number;
  category?: string;
  city?: string;
}

export interface TripDay {
  day: number;
  title?: string;
  weather_note?: string;
  items: TripItem[];
}

export interface Accommodation {
  name: string;
  days?: number[];
  location_note?: string;
  commute_note?: string;
  price_note?: string;
  detail?: string;
}

export interface Trip {
  itinerary: {
    days: TripDay[];
    summary?: string;
    warnings?: string[];
    accommodation?: Accommodation[];
  };
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
}

export default function TripView({ trip }: Props) {
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
            suggested_time: it.suggested_time,
            time_reason: it.time_reason,
            note: it.note,
          })),
      })),
    [days],
  );

  const budget = trip.budget_plan ?? {};
  // activeDay 防悬挂：重规划后天数变少时（如第3天被裁掉），
  // 将不存在的 tab 钳制回 "all"，避免 Tabs 无匹配项 + 地图/日卡空白
  const active =
    activeDay === "all" || days.some((d) => String(d.day) === activeDay)
      ? activeDay
      : "all";
  const visibleDays =
    active === "all"
      ? days
      : days.filter((d) => String(d.day) === active);

  const tabItems = [
    { key: "all", label: "全部" },
    ...days.map((d) => ({ key: String(d.day), label: `第${d.day}天` })),
  ];

  return (
    <div className="space-y-4">
      {/* 按天过滤 tabs */}
      <Tabs activeKey={active} onChange={setActiveDay} items={tabItems} />

      {/* 地图：保持纯 div 容器（leaflet 需要零内边距，不包 Card） */}
      <div className="h-[40vh] min-h-64 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <ItineraryMap
          days={geoDays}
          activeDay={active === "all" ? "all" : Number(active)}
        />
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
                <div>
                  <span className="text-slate-800">{it.name}</span>
                  {it.note && (
                    <span className="ml-1 text-xs text-slate-500">
                      （{it.note}）
                    </span>
                  )}
                  {it.suggested_time && (
                    <div className="mt-0.5 flex items-center gap-1 text-xs text-slate-500">
                      <ClockCircleOutlined className="text-brand" />
                      <span>建议{it.suggested_time}</span>
                      {it.time_reason && <span>（{it.time_reason}）</span>}
                    </div>
                  )}
                  {it.detail && (
                    <p className="mt-1 text-sm leading-relaxed text-slate-600">
                      {it.detail}
                    </p>
                  )}
                  {(it.poi_id || it.category === "attraction") && (
                    <AttractionImage name={it.name} city={it.city} />
                  )}
                </div>
              ),
            }))}
          />
        </Card>
      ))}

      {/* 住宿推荐（行程级 1-2 家：基于景点位置与通勤集中安排，跨区远才换宿） */}
      {trip.itinerary.accommodation?.length ? (
        <Card title="住宿推荐">
          <ul className="space-y-3">
            {trip.itinerary.accommodation.map((a, i) => (
              <li key={i} className="text-sm">
                <div className="flex flex-wrap items-center gap-1.5">
                  <HomeOutlined className="text-brand" />
                  <span className="font-medium text-slate-800">{a.name}</span>
                  {a.days?.length ? (
                    <Tag>{`第${a.days.join("、")}天`}</Tag>
                  ) : null}
                </div>
                {(a.location_note ||
                  a.commute_note ||
                  a.price_note ||
                  a.detail) && (
                  <div className="mt-1 space-y-0.5 pl-6 text-xs text-slate-500">
                    {a.location_note && <div>位置：{a.location_note}</div>}
                    {a.commute_note && <div>通勤：{a.commute_note}</div>}
                    {a.price_note && <div>价格：{a.price_note}</div>}
                    {a.detail && <div>环境：{a.detail}</div>}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {/* 预算卡片 */}
      {budget.items?.length ? (
        <Card title="预算分配">
          <Table<BudgetRow>
            size="small"
            pagination={false}
            rowKey="key"
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

    </div>
  );
}
