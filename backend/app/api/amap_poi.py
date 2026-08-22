"""高德 POI 检索：行程餐厅/酒店候选（真实商家，替代 LLM 编造的示例数据）。

调 restapi.amap.com/v3/place/text（extensions=all 才有 photos 字段）。
AMAP_KEY 未配置 / 请求失败 / status!=1 → 返回 []（planner 降级为示例数据模式）。
http_get 可注入，测试全 mock 无网络。评分/人均价高德实测不返回，不处理。
"""
from __future__ import annotations

import colorsys
import io
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from fastapi import APIRouter
from PIL import Image

AMAP_URL = "https://restapi.amap.com/v3/place/text"
FOOD_TYPE = "050000"    # 餐饮服务
HOTEL_TYPE = "100000"   # 住宿服务
FOOD_MAIN = "餐饮服务"
HOTEL_MAIN = "住宿服务"
BRANCH_SUFFIX_RE = re.compile(r"[（(][^（()）]{0,10}店[）)]$")  # 分店后缀（观锦餐厅(天府新谷店)）
MIN_PHOTO_SCORE = 100.0  # 照片"阳光指数"下限：低于此分判太暗/太灰，酒店换通用大堂图


def _score_photo(data: bytes) -> float:
    """照片"阳光指数"：明亮/高饱和/暖色加分，暗区减分；解码失败返回 -1。

    小宾馆照片常有昏黄灰败的第一张，按此分在多张里择优、低于阈值换兜底图。
    """
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return -1.0
    img.thumbnail((80, 80))  # 缩到 80px 内再统计，速度快且不受原图尺寸影响
    raw = img.tobytes()
    n = max(len(raw) // 3, 1)
    bright = dark = 0
    sat = 0.0
    sum_r = sum_b = 0
    for i in range(0, len(raw) - 2, 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        v = r + g + b
        if v >= 540:            # 平均 ≥180 算亮
            bright += 1
        elif v < 210:           # 平均 <70 算暗
            dark += 1
        mx = max(r, g, b)
        if mx:
            sat += (mx - min(r, g, b)) / mx
        sum_r += r
        sum_b += b
    sat_pct = sat / n * 100
    bright_pct = bright / n * 100
    dark_pct = dark / n * 100
    warm = min(max((sum_r - sum_b) / n, -10.0), 50.0)  # R-B 差值（蓝灰夜景为负）
    return sat_pct * 1.5 + bright_pct + warm * 1.5 - dark_pct * 2.0


def _fetch_photo(url: str) -> bytes | None:
    """下载照片字节（失败/超时返回 None，不拖垮整轮检索）。"""
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=2)
        if resp.status_code == 200 and resp.content:
            return resp.content
    except (requests.RequestException, TimeoutError, OSError):
        pass
    return None


def _pick_best_photo(urls: list[str], fetch=None) -> str | None:
    """在酒店多张照片里挑"阳光指数"最高的一张；全部低于阈值返回 None（走通用大堂图）。"""
    if not urls:
        return None
    fetch = fetch or _fetch_photo
    scores: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(fetch, u): u for u in dict.fromkeys(urls)}
        for fut in as_completed(futures):
            data = fut.result()
            if data:
                scores[futures[fut]] = _score_photo(data)
    if not scores:
        return None
    best = max(scores, key=scores.get)
    return best if scores[best] >= MIN_PHOTO_SCORE else None


def _default_hotel_fallback(city: str) -> str | None:
    """酒店真实照片全太暗：用"城市+酒店大堂"通用美图（必应首图，非该酒店实景）。"""
    from app.api.attraction_image import service as _image_service

    return _image_service.get_image_url("酒店 大堂", city)


class AmapPoiService:
    """高德 POI 搜索 → 过滤主分类 → 分店去重 → 解析为候选条目。"""

    def __init__(self, http_get=None, photo_picker=None, hotel_fallback=None) -> None:
        self.http_get = http_get or requests.get
        self.photo_picker = photo_picker or _pick_best_photo   # 酒店照片择优（测试注入替身）
        self.hotel_fallback = hotel_fallback or _default_hotel_fallback

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
        try:
            data = resp.json()
        except (ValueError, TypeError):
            return []  # 200 但非 JSON（HTML 网关页/代理页）→ 降级 []
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
            try:
                loc = str(p.get("location") or "")
                if "," not in loc:
                    continue
                lng, lat = loc.split(",", 1)
                lat_f = float(lat)
                lng_f = float(lng)
                photos = p.get("photos") or []
                photo_urls = [ph.get("url") for ph in photos
                              if isinstance(ph, dict) and ph.get("url")]
                photo_url = None
                if category == "hotel":
                    # 小宾馆第一张常昏黄灰暗：多张择优，全太暗换"城市+酒店大堂"通用图
                    photo_url = self.photo_picker(photo_urls) or self.hotel_fallback(city)
                elif photo_urls:
                    photo_url = photo_urls[0]  # 餐厅照片照旧取第一张
                out.append({
                    "poi_id": f"amap-{p.get('id')}",
                    "name": name, "city": city, "category": category,
                    "lat": lat_f, "lng": lng_f,
                    "address": str(p.get("address") or "").strip() or None,
                    "tel": str(p.get("tel") or "").strip() or None,
                    "photo_url": photo_url,
                })
                seen.add(base)  # 解析成功才占去重位（坏坐标不毒化去重链）
            except (ValueError, TypeError, AttributeError, KeyError):
                continue  # 坏条目跳过，好条目保留（不整轮失败）
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
