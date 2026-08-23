import { useMemo, useRef, useState } from "react";
import { Card, Table, Tabs, Tag, Timeline } from "antd";
import type { TableProps } from "antd";
import {
  BulbOutlined,
  ClockCircleOutlined,
  CloudOutlined,
  EnvironmentOutlined,
  HomeOutlined,
} from "@ant-design/icons";
import AttractionImage from "./AttractionImage";
import ItineraryMap, { type DayGeo, type MapFocus } from "./ItineraryMap";

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
  // 高德真实商家（餐厅/酒店）：地址/电话/照片
  address?: string;
  tel?: string;
  photo_url?: string;
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
  // 高德真实商家（酒店）：poi_id/地址/电话/照片 + 坐标（地图蓝点）
  poi_id?: string;
  category?: string;
  city?: string;
  lat?: number;
  lng?: number;
  address?: string;
  tel?: string;
  photo_url?: string;
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
  pct?: number;
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
  {
    title: "占比",
    dataIndex: "pct",
    align: "right",
    width: 70,
    render: (v: number) => <span className="text-slate-400">{v}%</span>,
  },
];

interface Props {
  trip: Trip;
}

export default function TripView({ trip }: Props) {
  const days = trip.itinerary.days ?? [];
  const [activeDay, setActiveDay] = useState<string>("all");
  // 点击条目 → 视口滚到地图 + 地图飞行定位（nonce 保证重复点击同一目标也能重新触发）
  const [focus, setFocus] = useState<MapFocus | null>(null);
  const [focusNonce, setFocusNonce] = useState(0);
  const mapRef = useRef<HTMLDivElement>(null);
  const locate = (name: string, lat: number, lng: number) => {
    mapRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    setFocus({ name, lat, lng });
    setFocusNonce((n) => n + 1);
  };

  // 带坐标的条目上地图（景点 + 高德真实餐厅/酒店 + 富化的住宿蓝点）
  const geoDays: DayGeo[] = useMemo(
    () =>
      days.map((d) => {
        const hotelPoints = (trip.itinerary.accommodation ?? [])
          .filter(
            (a): a is Accommodation & { lat: number; lng: number } =>
              (a.days ?? []).includes(d.day) &&
              typeof a.lat === "number" &&
              typeof a.lng === "number",
          )
          .map((a) => ({
            name: a.name,
            lat: a.lat,
            lng: a.lng,
            category: "hotel",
            address: a.address,
          }));
        return {
          day: d.day,
          title: d.title,
          points: [
            ...(d.items ?? [])
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
                category: it.category,
                address: it.address,
              })),
            ...hotelPoints,
          ],
        };
      }),
    [days, trip.itinerary.accommodation],
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
      <div
        ref={mapRef}
        className="h-[55vh] min-h-96 scroll-mt-2 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
      >
        <ItineraryMap
          days={geoDays}
          activeDay={active === "all" ? "all" : Number(active)}
          focus={focus}
          focusNonce={focusNonce}
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
                  <span
                    className={
                      typeof it.lat === "number" && typeof it.lng === "number"
                        ? "cursor-pointer text-slate-800 hover:text-brand"
                        : "text-slate-800"
                    }
                    title="在地图上定位"
                    onClick={() => {
                      if (typeof it.lat === "number" && typeof it.lng === "number") {
                        locate(it.name, it.lat, it.lng);
                      }
                    }}
                  >
                    {it.name}
                  </span>
                  {typeof it.lat === "number" && typeof it.lng === "number" && (
                    <EnvironmentOutlined className="ml-1 text-xs text-brand/60" />
                  )}
                  {it.note && (
                    <span className="ml-1 text-xs text-slate-500">
                      （{it.note}）
                    </span>
                  )}
                  {it.suggested_time && (
                    <div className="mt-0.5 flex items-center gap-1 text-xs text-slate-500">
                      <ClockCircleOutlined className="text-brand" />
                      <span>建议{it.suggested_time.replace(/^建议/, "")}</span>
                      {it.time_reason && <span>（{it.time_reason}）</span>}
                    </div>
                  )}
                  {it.address && (
                    <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-slate-500">
                      <span>
                        <EnvironmentOutlined className="mr-0.5 text-brand" />
                        {it.address}
                      </span>
                    </div>
                  )}
                  {it.detail && (
                    <p className="mt-1 text-sm leading-relaxed text-slate-600">
                      {it.detail}
                    </p>
                  )}
                  {(it.poi_id || it.category === "attraction") && (
                    <AttractionImage name={it.name} city={it.city} photoUrl={it.photo_url} />
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
                  <span
                    className={
                      typeof a.lat === "number" && typeof a.lng === "number"
                        ? "cursor-pointer font-medium text-slate-800 hover:text-brand"
                        : "font-medium text-slate-800"
                    }
                    title="在地图上定位"
                    onClick={() => {
                      if (typeof a.lat === "number" && typeof a.lng === "number") {
                        locate(a.name, a.lat, a.lng);
                      }
                    }}
                  >
                    {a.name}
                  </span>
                  {a.days?.length ? (
                    <Tag>{`第${a.days.join("、")}天`}</Tag>
                  ) : null}
                </div>
                {a.address && (
                  <div className="mt-1 flex flex-wrap gap-x-3 pl-6 text-xs text-slate-500">
                    <span>
                      <EnvironmentOutlined className="mr-0.5 text-brand" />
                      {a.address}
                    </span>
                  </div>
                )}
                <div className="pl-6">
                  <AttractionImage
                    name={a.name}
                    city={a.city}
                    photoUrl={a.photo_url}
                  />
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
            dataSource={budget.items.map((it, i) => ({
              key: i,
              ...it,
              pct: budget.total ? Math.round((it.amount / budget.total) * 100) : undefined,
            }))}
            footer={
              budget.total != null
                ? () => `合计 ¥${budget.total}`
                : undefined
            }
          />
        </Card>
      ) : null}

      {/* 总结 + tips + 警示 */}
      {trip.itinerary.summary || trip.summary || trip.tips?.length || trip.itinerary.warnings?.length ? (
        <Card title="行程总结">
          {(trip.itinerary.summary || trip.summary) && (
            <p className="text-sm leading-relaxed text-slate-800">
              {trip.itinerary.summary || trip.summary}
            </p>
          )}
          {trip.itinerary.summary && trip.summary && (
            <p className="mt-2 text-xs text-slate-500">总体建议：{trip.summary}</p>
          )}
          {trip.itinerary.warnings?.length ? (
            <ul className="mt-2 space-y-1 text-sm">
              {trip.itinerary.warnings.map((w, i) => (
                <li key={i} className="text-amber-600">
                  ⚠️ {w}
                </li>
              ))}
            </ul>
          ) : null}
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

      <p className="text-center text-xs text-slate-400">
        餐厅/酒店数据来自高德地图，营业信息可能变动
      </p>
    </div>
  );
}
