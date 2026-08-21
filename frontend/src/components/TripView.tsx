import { useMemo, useState } from "react";
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

interface Props {
  trip: Trip;
  reply: string;
}

export default function TripView({ trip, reply }: Props) {
  const days = trip.itinerary.days ?? [];
  const [activeDay, setActiveDay] = useState<number | "all">("all");

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
          .map((it) => ({ name: it.name, lat: it.lat, lng: it.lng, time: it.time, note: it.note })),
      })),
    [days],
  );

  const budget = trip.budget_plan ?? {};
  const visibleDays = activeDay === "all" ? days : days.filter((d) => d.day === activeDay);

  return (
    <div className="space-y-4">
      {/* 按天过滤 tabs */}
      <div className="flex flex-wrap gap-2">
        <button
          className={`rounded-full px-3 py-1 text-xs ${activeDay === "all" ? "bg-blue-600 text-white" : "bg-white text-slate-600 border border-slate-300"}`}
          onClick={() => setActiveDay("all")}
        >
          全部
        </button>
        {days.map((d) => (
          <button
            key={d.day}
            className={`rounded-full px-3 py-1 text-xs ${activeDay === d.day ? "bg-blue-600 text-white" : "bg-white text-slate-600 border border-slate-300"}`}
            onClick={() => setActiveDay(d.day)}
          >
            第{d.day}天
          </button>
        ))}
      </div>

      {/* 地图 */}
      <div className="h-[40vh] min-h-64 overflow-hidden rounded-xl border border-slate-200">
        <ItineraryMap days={geoDays} activeDay={activeDay} />
      </div>

      {/* 日卡 */}
      <div className="grid gap-3">
        {visibleDays.map((d) => (
          <div key={d.day} className="rounded-xl border border-slate-200 bg-white p-4">
            <h3 className="font-semibold text-slate-800">第 {d.day} 天：{d.title ?? ""}</h3>
            {d.weather_note && <p className="mt-0.5 text-xs text-slate-500">🌤 {d.weather_note}</p>}
            <ul className="mt-3 space-y-2">
              {(d.items ?? []).map((it, i) => (
                <li key={i} className="flex gap-2 text-sm">
                  <span className="shrink-0 font-mono text-slate-400">{it.time ?? "--:--"}</span>
                  <span className="text-slate-800">{it.name}</span>
                  {it.note && <span className="self-center text-xs text-slate-500">（{it.note}）</span>}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* 预算卡片 */}
      {budget.items?.length ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <h3 className="mb-2 font-semibold text-slate-800">预算分配</h3>
          <table className="w-full text-sm">
            <tbody>
              {budget.items.map((it, i) => (
                <tr key={i} className="border-b border-slate-100 last:border-0">
                  <td className="py-1.5">{it.category}</td>
                  <td className="py-1.5 text-xs text-slate-500">{it.note}</td>
                  <td className="py-1.5 text-right font-mono">{it.amount}</td>
                </tr>
              ))}
              {budget.total != null && (
                <tr>
                  <td className="py-1.5 font-semibold">合计</td>
                  <td />
                  <td className="py-1.5 text-right font-mono font-semibold">{budget.total}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : null}

      {/* 总结 + tips */}
      {trip.summary || trip.tips?.length ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
          {trip.summary && <p className="text-slate-800">{trip.summary}</p>}
          {trip.tips?.length ? (
            <ul className="mt-2 space-y-1">
              {trip.tips.map((t, i) => (
                <li key={i} className="text-slate-600">💡 {t}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {/* 完整文本回复折叠 */}
      <details className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
        <summary className="cursor-pointer select-none text-xs text-slate-500">查看完整文本回复</summary>
        <div className="mt-2 whitespace-pre-wrap text-slate-800">{reply}</div>
      </details>
    </div>
  );
}
