"""天气适配器：Open-Meteo（免 key）真实 API + 失败降级为模拟数据。

成功数据 source="open-meteo"，降级数据 source="simulated"（确定性生成），
调用方（Planner）无需区分即可使用。
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any

import httpx

BASE_URL = "https://api.open-meteo.com/v1/forecast"

# https://open-meteo.com/en/docs 的 WMO weather code → 中文
WEATHERCODES: dict[int, str] = {
    0: "晴", 1: "多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    56: "冻雨", 57: "冻雨",
    61: "雨", 63: "雨", 65: "雨",
    66: "冻雨", 67: "冻雨",
    71: "雪", 73: "雪", 75: "雪", 77: "雪",
    80: "阵雨", 81: "阵雨", 82: "阵雨",
    85: "阵雪", 86: "阵雪",
    95: "雷暴", 96: "雷暴", 99: "雷暴",
}


def _condition_cn(code: int) -> str:
    return WEATHERCODES.get(code, "未知")


def _simulated_weather(lat: float, lng: float, days: int) -> list[dict]:
    """确定性模拟：让 Planner 的测试与演示离线可用。"""
    today = dt.date.today()
    seed = int((lat * 10 + lng * 7 + time.time() // 86400) % 3)
    conditions = ["晴", "多云", "雨"]
    out = []
    for i in range(days):
        d = today + dt.timedelta(days=i)
        out.append({
            "date": d.isoformat(),
            "t_max": round(24 + seed + (i % 3) * 2, 1),
            "t_min": round(15 + seed - (i % 2), 1),
            "condition": conditions[(seed + i) % len(conditions)],
            "source": "simulated",
        })
    return out


def get_weather(
    lat: float,
    lng: float,
    *,
    days: int = 5,
    client: httpx.Client | None = None,
) -> list[dict]:
    """查询未来 days 天逐日天气；任何失败都降级为模拟数据（不抛出）。"""
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=10)
    try:
        resp = client.get(
            BASE_URL,
            params={
                "latitude": lat,
                "longitude": lng,
                "daily": "temperature_2m_max,temperature_2m_min,weathercode",
                "timezone": "auto",
                "forecast_days": days,
            },
        )
        resp.raise_for_status()
        daily: dict[str, Any] = resp.json()["daily"]
        times = daily["time"]
        t_max = daily["temperature_2m_max"]
        t_min = daily["temperature_2m_min"]
        codes = daily["weathercode"]
        return [
            {
                "date": times[i],
                "t_max": t_max[i],
                "t_min": t_min[i],
                "condition": _condition_cn(codes[i]),
                "source": "open-meteo",
            }
            for i in range(min(days, len(times)))
        ]
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return _simulated_weather(lat, lng, days)
    finally:
        if own_client:
            client.close()
