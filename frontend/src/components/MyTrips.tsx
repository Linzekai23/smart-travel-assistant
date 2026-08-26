import { useEffect, useState } from "react";
import { Button, Empty, Popconfirm, Spin } from "antd";
import { ArrowLeftOutlined, DeleteOutlined, CalendarOutlined } from "@ant-design/icons";
import TripView, { type Trip } from "./TripView";

interface TripMeta {
  id: string;
  title: string;
  days: number | null;
  created_at: string;
  updated_at: string;
}

export default function MyTrips() {
  const [trips, setTrips] = useState<TripMeta[] | null>(null);
  const [selected, setSelected] = useState<TripMeta | null>(null);
  const [detail, setDetail] = useState<Trip | null>(null);

  const load = () => {
    fetch("/api/trips")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setTrips(data?.trips ?? []))
      .catch(() => setTrips([]));
  };
  useEffect(load, []);

  const openTrip = (meta: TripMeta) => {
    setSelected(meta);
    setDetail(null);
    fetch(`/api/trips/${encodeURIComponent(meta.id)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setDetail(data?.trip_json ?? null))
      .catch(() => setDetail(null));
  };

  const remove = (id: string) => {
    fetch(`/api/trips/${encodeURIComponent(id)}`, { method: "DELETE" })
      .then((r) => {
        if (r.ok) load();
      })
      .catch(() => {});
  };

  // 详情视图：返回按钮 + 只读复用 TripView
  if (selected) {
    return (
      <div className="mx-auto max-w-4xl p-4 md:p-6">
        <div className="mb-3 flex items-center justify-between">
          <Button icon={<ArrowLeftOutlined />} onClick={() => setSelected(null)}>
            返回列表
          </Button>
          <span className="font-medium text-slate-700">{selected.title}</span>
        </div>
        {detail ? (
          <TripView trip={detail} />
        ) : (
          <div className="flex justify-center py-16">
            <Spin />
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl p-4 md:p-6">
      <h2 className="mb-4 text-lg font-semibold text-slate-800">我的行程</h2>
      {trips === null ? (
        <div className="flex justify-center py-16">
          <Spin />
        </div>
      ) : trips.length === 0 ? (
        <Empty description="还没有保存的行程——在智能旅行助手里生成行程后，点击「保存到我的行程」即可收藏" />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {trips.map((t) => (
            <div
              key={t.id}
              className="group flex cursor-pointer items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-brand/40 hover:shadow"
              onClick={() => openTrip(t)}
            >
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-slate-800">{t.title}</div>
                <div className="mt-1 flex items-center gap-3 text-xs text-slate-500">
                  {t.days != null && (
                    <span>
                      <CalendarOutlined className="mr-0.5 text-brand" />
                      {t.days} 天行程
                    </span>
                  )}
                  <span>更新于 {t.updated_at}</span>
                </div>
              </div>
              <Popconfirm
                title="删除该行程？"
                description="删除后不可恢复"
                onConfirm={(e) => {
                  e?.stopPropagation();
                  remove(t.id);
                }}
              >
                <Button
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={(e) => e.stopPropagation()}
                  className="opacity-0 transition group-hover:opacity-100"
                />
              </Popconfirm>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
