import { useEffect, useMemo } from "react";
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import { BRAND } from "../theme";

export interface MapPoint {
  name: string;
  lat: number;
  lng: number;
  time?: string;
  note?: string;
}

export interface DayGeo {
  day: number;
  title?: string;
  points: MapPoint[];
}

// 高德瓦片（无 key；GCJ-02 与语料近似坐标的偏移由"坐标仅供参考"免责声明覆盖）
const TILE_URL =
  "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}";

// 自定义 divIcon：bundler 下 Leaflet 默认 marker 图标资源会 404，圆形编号标记规避
function makeIcon(day: number, index: number) {
  return L.divIcon({
    className: "",
    html: `<div style="background:${BRAND};color:#fff;border-radius:9999px;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:11px;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)">${day}-${index + 1}</div>`,
    iconSize: [20, 20],
    iconAnchor: [10, 10],
  });
}

function FitBounds({ points }: { points: MapPoint[] }) {
  const map = useMap();
  useEffect(() => {
    if (!points.length) return;
    const bounds = L.latLngBounds(points.map((p) => [p.lat, p.lng] as [number, number]));
    map.fitBounds(bounds, { padding: [30, 30], maxZoom: 13 });
  }, [map, points]);
  return null;
}

interface Props {
  days: DayGeo[];
  activeDay: number | "all";
}

export default function ItineraryMap({ days, activeDay }: Props) {
  const visibleDays = useMemo(
    () => (activeDay === "all" ? days : days.filter((d) => d.day === activeDay)),
    [days, activeDay],
  );
  const points = useMemo(() => visibleDays.flatMap((d) => d.points), [visibleDays]);

  return (
    <div className="relative h-full w-full">
      <MapContainer center={[35, 105]} zoom={4} className="h-full w-full" scrollWheelZoom={false}>
        <TileLayer
          url={TILE_URL}
          subdomains={["1", "2", "3", "4"]}
          maxZoom={18}
          attribution="© 高德地图"
        />
        <FitBounds points={points} />
        {visibleDays.map((d) =>
          d.points.map((p, i) => (
            <Marker key={`${d.day}-${i}`} position={[p.lat, p.lng]} icon={makeIcon(d.day, i)}>
              <Popup>
                <div className="text-xs">
                  <p className="font-semibold">{p.name}</p>
                  {p.time && <p>时间：{p.time}</p>}
                  {p.note && <p>{p.note}</p>}
                </div>
              </Popup>
            </Marker>
          )),
        )}
        {visibleDays.map((d) =>
          d.points.length >= 2 ? (
            <Polyline
              key={`line-${d.day}`}
              positions={d.points.map((p) => [p.lat, p.lng] as [number, number])}
              pathOptions={{ color: BRAND, weight: 3, dashArray: "6 4" }}
            />
          ) : null,
        )}
      </MapContainer>
      <p className="absolute bottom-0 left-0 z-[1000] rounded-tr bg-white/90 px-2 py-0.5 text-[10px] text-slate-500">
        AI 生成示例数据，坐标仅供参考
      </p>
    </div>
  );
}
