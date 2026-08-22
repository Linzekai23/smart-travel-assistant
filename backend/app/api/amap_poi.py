"""高德 POI 检索：行程餐厅/酒店候选（真实商家，替代 LLM 编造的示例数据）。

调 restapi.amap.com/v3/place/text（extensions=all 才有 photos 字段）。
AMAP_KEY 未配置 / 请求失败 / status!=1 → 返回 []（planner 降级为示例数据模式）。
http_get 可注入，测试全 mock 无网络。评分/人均价高德实测不返回，不处理。
"""
from __future__ import annotations

import os
import re
import urllib.parse

import requests
from fastapi import APIRouter

AMAP_URL = "https://restapi.amap.com/v3/place/text"
FOOD_TYPE = "050000"    # 餐饮服务
HOTEL_TYPE = "100000"   # 住宿服务
FOOD_MAIN = "餐饮服务"
HOTEL_MAIN = "住宿服务"
BRANCH_SUFFIX_RE = re.compile(r"[（(][^（()）]{0,10}店[）)]$")  # 分店后缀（观锦餐厅(天府新谷店)）


class AmapPoiService:
    """高德 POI 搜索 → 过滤主分类 → 分店去重 → 解析为候选条目。"""

    def __init__(self, http_get=None) -> None:
        self.http_get = http_get or requests.get

    def search_restaurants(self, city: str) -> list[dict]:
        return self._search(city, FOOD_TYPE, FOOD_MAIN, "restaurant")

    def search_hotels(self, city: str) -> list[dict]:
        return self._search(city, HOTEL_TYPE, HOTEL_MAIN, "hotel")

    def _search(self, city: str, poi_type: str, main_type: str, category: str) -> list[dict]:
        key = os.environ.get("AMAP_KEY")
        if not key:
            return []  # 无 key：planner 走示例数据模式
        q = urllib.parse.urlencode({
            "key": key, "city": city, "citylimit": "true",
            "offset": "20", "page": "1", "extensions": "all"})
        try:
            resp = self.http_get(f"{AMAP_URL}?{q}&types={poi_type}", timeout=8)
        except (requests.RequestException, TimeoutError, OSError):
            return []
        if getattr(resp, "status_code", 200) != 200:
            return []
        data = resp.json()
        if not isinstance(data, dict) or data.get("status") != "1":
            return []
        out: list[dict] = []
        seen: set[str] = set()
        for p in data.get("pois") or []:
            if not isinstance(p, dict) or not str(p.get("type") or "").startswith(main_type):
                continue  # 裸搜会混入其他分类（如美食结果里的住宿服务）
            name = str(p.get("name") or "").strip()
            base = BRANCH_SUFFIX_RE.sub("", name)
            if not name or base in seen:
                continue  # 同一连锁分店只留第一条
            seen.add(base)
            loc = str(p.get("location") or "")
            if "," not in loc:
                continue
            lng, lat = loc.split(",", 1)
            photos = p.get("photos") or []
            out.append({
                "poi_id": f"amap-{p.get('id')}",
                "name": name, "city": city, "category": category,
                "lat": float(lat), "lng": float(lng),
                "address": str(p.get("address") or "").strip() or None,
                "tel": str(p.get("tel") or "").strip() or None,
                "photo_url": photos[0].get("url") if photos else None,
            })
            if len(out) >= 10:
                break
        return out


router = APIRouter()


@router.get("/api/amap-poi")
def amap_poi(city: str, type: str = "restaurant") -> dict:
    """调试/演示：查目的地真实餐厅/酒店候选（type: restaurant|hotel）。"""
    if type == "hotel":
        return {"items": service.search_hotels(city)}
    return {"items": service.search_restaurants(city)}


service = AmapPoiService()
