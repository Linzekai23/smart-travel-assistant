"""高德路线规划：独立交通查询页（起终点文本 → geocode → 路线）。

调 restapi.amap.com/v3/{geocode/geo, direction/transit/integrated, direction/driving, direction/walking}。
AMAP_KEY 未配置 → 返回 no_key 提示；geocode 失败 → geocode_fail；路线 API 失败 →
降级 haversine 直线距离（source=estimate，标注仅供参考）。http_get 可注入，测试全 mock。
"""
from __future__ import annotations

import math
import os
import urllib.parse

import requests
from fastapi import APIRouter, Query

GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
TRANSIT_URL = "https://restapi.amap.com/v3/direction/transit/integrated"
DRIVING_URL = "https://restapi.amap.com/v3/direction/driving"
WALKING_URL = "https://restapi.amap.com/v3/direction/walking"


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点直线距离（公里），离线兜底用。"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _minutes(seconds) -> int | None:
    """秒 → 分钟（向上取整）；非法值返回 None。"""
    try:
        return max(1, math.ceil(int(seconds) / 60))
    except (ValueError, TypeError):
        return None


def _km(meters) -> float | None:
    """米 → 公里（保留 1 位）；非法值返回 None。"""
    try:
        return round(int(meters) / 1000, 1)
    except (ValueError, TypeError):
        return None


def _cost_yuan(value) -> int | None:
    """票价/收费金额：0 或缺失视为免费，返回 None（前端不显示）；非法值 None。"""
    try:
        v = float(value)
    except (ValueError, TypeError):
        return None
    return int(v) if v > 0 else None


def _transit_summary(transit: dict) -> str | None:
    """公交方案摘要：取公交/地铁线名（去重，最多 2 条），如"地铁1号线、公交52路"。"""
    names: list[str] = []
    for seg in transit.get("segments") or []:
        bus = seg.get("bus") or {}
        for line in bus.get("buslines") or []:
            name = str(line.get("name") or "").strip()
            if name and name not in names:
                names.append(name)
        if len(names) >= 2:
            break
    return "、".join(names) if names else None


def _parse_polyline(raw: str | None) -> list[list[float]]:
    """高德 polyline 字符串 "lng,lat;lng,lat;..." → [[lat, lng], ...]（Leaflet 顺序）。

    坏坐标/非法行跳过，整体解析失败返回 []（地图画线是锦上添花，不阻塞结果）。
    """
    points: list[list[float]] = []
    for part in (raw or "").split(";"):
        try:
            lng, lat = part.split(",", 1)
            points.append([float(lat), float(lng)])
        except (ValueError, TypeError):
            continue
    return points


def _concat_polylines(polylines: list) -> list[list[float]]:
    """多条 polyline 字符串拼接为一条连续路线（去掉相邻段重复的首尾点）。"""
    out: list[list[float]] = []
    for poly in polylines:
        pts = _parse_polyline(poly)
        if not pts:
            continue
        if out and out[-1] == pts[0]:
            pts = pts[1:]  # 相邻段共享接点
        out.extend(pts)
    return out


class AmapRouteService:
    """高德 geocode + 路线查询；任何失败返回 None（降级由调用方处理）。"""

    def __init__(self, http_get=None) -> None:
        self.http_get = http_get or requests.get

    def _get_json(self, url: str, params: dict) -> dict | None:
        key = os.environ.get("AMAP_KEY")
        if not key:
            return None
        q = urllib.parse.urlencode({**params, "key": key})
        try:
            resp = self.http_get(f"{url}?{q}", timeout=8)
        except (requests.RequestException, TimeoutError, OSError):
            return None
        if resp is None or getattr(resp, "status_code", 200) != 200:
            return None
        try:
            data = resp.json()
        except (ValueError, TypeError, AttributeError):
            return None  # 200 但非 JSON（HTML 网关页）→ None
        if not isinstance(data, dict) or data.get("status") != "1":
            return None
        return data

    def geocode(self, city: str, name: str) -> dict | None:
        """地名 → 坐标 {"lat", "lng"}；定位失败返回 None。"""
        data = self._get_json(GEOCODE_URL, {"address": name, "city": city})
        if not data:
            return None
        for item in data.get("geocodes") or []:
            loc = str(item.get("location") or "")
            if "," not in loc:
                continue
            lng, lat = loc.split(",", 1)
            try:
                return {"lat": float(lat), "lng": float(lng)}
            except (ValueError, TypeError):
                continue
        return None

    def route(self, from_ll: dict, to_ll: dict, mode: str = "transit",
              city: str = "") -> dict | None:
        """起终点坐标 → 路线结果；任何失败返回 None（降级为直线距离）。"""
        origin = f"{from_ll['lng']},{from_ll['lat']}"
        destination = f"{to_ll['lng']},{to_ll['lat']}"

        if mode == "driving":
            data = self._get_json(DRIVING_URL, {
                "origin": origin, "destination": destination, "strategy": "10"})
            if not data:
                return None
            paths = (data.get("route") or {}).get("paths") or []
            if not paths:
                return None
            p = paths[0]
            return {"duration_min": _minutes(p.get("duration")),
                    "distance_km": _km(p.get("distance")),
                    "cost_yuan": _cost_yuan(p.get("tolls")),
                    "summary": None,
                    "polyline": _concat_polylines(
                        [s.get("polyline") for s in (p.get("steps") or [])])}

        if mode == "walking":
            data = self._get_json(WALKING_URL, {
                "origin": origin, "destination": destination})
            if not data:
                return None
            paths = (data.get("route") or {}).get("paths") or []
            if not paths:
                return None
            p = paths[0]
            return {"duration_min": _minutes(p.get("duration")),
                    "distance_km": _km(p.get("distance")),
                    "cost_yuan": None, "summary": None,
                    "polyline": _concat_polylines(
                        [s.get("polyline") for s in (p.get("steps") or [])])}

        # transit（默认，公交/地铁）
        data = self._get_json(TRANSIT_URL, {
            "origin": origin, "destination": destination,
            "city": city, "cityd": city, "strategy": "0"})
        if not data:
            return None
        transits = (data.get("route") or {}).get("transits") or []
        if not transits:
            return None
        t = transits[0]
        # 路线几何：各段拼接（公交/地铁段取 buslines[0].polyline，步行段取 walking.polyline）
        seg_polylines: list = []
        for seg in t.get("segments") or []:
            bus = seg.get("bus") or {}
            buslines = bus.get("buslines") or []
            if buslines and buslines[0].get("polyline"):
                seg_polylines.append(buslines[0].get("polyline"))
            else:
                seg_polylines.append((seg.get("walking") or {}).get("polyline"))
        return {"duration_min": _minutes(t.get("duration")),
                "distance_km": _km(t.get("distance")),
                "cost_yuan": _cost_yuan(t.get("cost")),
                "summary": _transit_summary(t),
                "polyline": _concat_polylines(seg_polylines)}


router = APIRouter()


@router.get("/api/route")
def route_plan(city: str = "",
               from_: str = Query("", alias="from"),
               to_: str = Query("", alias="to"),
               mode: str = "transit",
               from_lng: float | None = None, from_lat: float | None = None,
               to_lng: float | None = None, to_lat: float | None = None) -> dict:
    """交通查询：起终点（文本，走高德 geocode）或直接坐标；mode: transit|driving|walking。

    返回 {ok, source(amap|estimate|no_key|geocode_fail), message?, ...路线字段}。
    """
    if not os.environ.get("AMAP_KEY"):
        return {"ok": False, "source": "no_key",
                "message": "未配置 AMAP_KEY，交通查询不可用（在 backend/.env 配置高德 Web 服务 key）"}

    svc = AmapRouteService()
    from_ll = {"lat": from_lat, "lng": from_lng} \
        if from_lng is not None and from_lat is not None else None
    to_ll = {"lat": to_lat, "lng": to_lng} \
        if to_lng is not None and to_lat is not None else None

    if from_ll is None:
        from_ll = svc.geocode(city, from_)
        if from_ll is None:
            return {"ok": False, "source": "geocode_fail", "message": f"未能定位「{from_}」"}
    if to_ll is None:
        to_ll = svc.geocode(city, to_)
        if to_ll is None:
            return {"ok": False, "source": "geocode_fail", "message": f"未能定位「{to_}」"}

    result = svc.route(from_ll, to_ll, mode, city)
    base = {"mode": mode, "from": from_, "to": to_}
    if result is None:
        # 降级：离线直线距离兜底（仍返回坐标，前端可展示）
        return {"ok": True, "source": "estimate",
                "message": "路线规划暂不可用，显示直线距离仅供参考",
                **base,
                "distance_km": round(_haversine_km(
                    from_ll["lat"], from_ll["lng"], to_ll["lat"], to_ll["lng"]), 1),
                "duration_min": None, "cost_yuan": None, "summary": None,
                "from_ll": from_ll, "to_ll": to_ll}
    return {"ok": True, "source": "amap", **base, **result,
            "from_ll": from_ll, "to_ll": to_ll}
