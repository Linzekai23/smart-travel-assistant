"""攻略浏览：按城市浏览景点/美食/住宿。

- 城市清单：PROVINCES 省内城市全清单（全国地级市，含库外城市——有高德 key 即可
  直接检索；无高德数据时该城市显示空状态）
- 景点：AmapPoiService 高德真实检索优先（风景名胜主分类）；无 key/失败/无结果
  → 读 poi_corpus.jsonl 按 city 过滤兜底（攻略浏览不需要语义检索）
- 美食/住宿：复用 AmapPoiService（高德实时检索）；无 AMAP_KEY → 空列表（前端提示）
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter

from app.api.amap_poi import service as amap_poi_service
from app.rag.province_cities import PROVINCES


@lru_cache(maxsize=1)
def _load_corpus() -> list[dict]:
    """语料全文（进程内缓存）；文件缺失/损坏 → []。

    路径在函数内读 env（模块级常量会在 import 时固定，测试无法覆盖路径）。
    """
    path = Path(os.environ.get("POI_CORPUS_PATH", "data/poi_corpus.jsonl"))
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _guide_cities() -> list[dict]:
    """可选城市清单：全国地级市（按省分组），与语料无关。"""
    return [{"province": province, "city": city}
            for province, d in PROVINCES.items()
            for city in d["cities"]]


router = APIRouter()


@router.get("/api/guide/cities")
def guide_cities() -> dict:
    """可选城市清单（前端 Select 分组用）。"""
    return {"cities": _guide_cities()}


@router.get("/api/guide")
def guide(city: str) -> dict:
    """某城市的景点（高德真实 POI 优先，无 key/失败/无结果 → 语料兜底）
    + 美食/住宿（高德，无 key 为空）。"""
    attractions = amap_poi_service.search_attractions(city)
    if not attractions:
        attractions = [
            p for p in _load_corpus()
            if p.get("city") == city and p.get("category") == "attraction"
        ]
    restaurants = amap_poi_service.search_restaurants(city)
    hotels = amap_poi_service.search_hotels(city)
    return {
        "city": city,
        "attractions": attractions,
        "restaurants": restaurants,
        "hotels": hotels,
        "amap_available": bool(os.environ.get("AMAP_KEY")),
    }
