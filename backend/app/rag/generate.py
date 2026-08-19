"""POI 语料生成：DeepSeek 按城市模板批量生成（一次一城，JSON 模式）。

产物是 backend/data/poi_corpus.jsonl，数据为 **AI 生成示例数据，
坐标仅供参考**（README 与前端展示均注明）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from app.llm.deepseek import DeepSeekProvider

CITIES = [
    "北京", "上海", "成都", "西安", "杭州", "广州", "深圳", "南京", "苏州",
    "重庆", "厦门", "青岛", "大连", "长沙", "武汉", "昆明", "大理", "丽江",
    "三亚", "洛阳",
]

CITY_EN = {
    "北京": "beijing", "上海": "shanghai", "成都": "chengdu", "西安": "xian",
    "杭州": "hangzhou", "广州": "guangzhou", "深圳": "shenzhen", "南京": "nanjing",
    "苏州": "suzhou", "重庆": "chongqing", "厦门": "xiamen", "青岛": "qingdao",
    "大连": "dalian", "长沙": "changsha", "武汉": "wuhan", "昆明": "kunming",
    "大理": "dali", "丽江": "lijiang", "三亚": "sanya", "洛阳": "luoyang",
}

# 城市中心坐标（用于生成时约束坐标范围与 ingest 校验）
CITY_COORDS: dict[str, tuple[float, float]] = {
    "北京": (39.9042, 116.4074), "上海": (31.2304, 121.4737), "成都": (30.5728, 104.0668),
    "西安": (34.3416, 108.9398), "杭州": (30.2741, 120.1551), "广州": (23.1291, 113.2644),
    "深圳": (22.5431, 114.0579), "南京": (32.0603, 118.7969), "苏州": (31.2989, 120.5853),
    "重庆": (29.5630, 106.5516), "厦门": (24.4798, 118.0894), "青岛": (36.0671, 120.3826),
    "大连": (38.9140, 121.6147), "长沙": (28.2282, 112.9388), "武汉": (30.5928, 114.3055),
    "昆明": (24.8801, 102.8329), "大理": (25.6065, 100.2676), "丽江": (26.8721, 100.2299),
    "三亚": (18.2528, 109.5119), "洛阳": (34.6197, 112.4540),
}

VALID_CATEGORIES = {"attraction", "restaurant", "hotel"}
VALID_TIERS = {1, 2, 3, 4}

GENERATE_SYSTEM_PROMPT = """你是中国旅游 POI 数据生成器。为指定城市生成景点/酒店/餐厅条目（AI 生成示例数据，坐标仅供参考，但要落在该城市市中心周边合理范围）。
只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{"city": "城市名", "pois": [
  {"name": "中文名", "category": "attraction|restaurant|hotel",
   "lat": 纬度, "lng": 经度, "rating": 3.5到5.0一位小数,
   "price_tier": 1到4整数, "description": "50字以内，真实、信息密度高",
   "tags": ["2-4个标签，如 历史/夜景/亲子/排队/免费"]}
]}
数量要求：景点 8-10 个、餐厅 5-6 家（含本地特色美食）、酒店 3-4 家（覆盖经济/舒适/高档价位）。"""


def generate_city(provider: DeepSeekProvider, city: str) -> list[dict]:
    """调用一次 DeepSeek 生成一城 POI，返回校验后的条目（含 city 字段）。"""
    lat, lng = CITY_COORDS[city]
    messages = [
        {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"请为「{city}」生成 POI 数据。市中心坐标约 ({lat}, {lng})，"
            "所有条目坐标必须在市中心 ±2 度范围内。只输出 JSON。"
        )},
    ]
    raw = provider.chat_json(messages)
    pois = raw.get("pois", []) if isinstance(raw, dict) else []
    return validate_pois(city, pois)


def validate_pois(city: str, pois: list[dict]) -> list[dict]:
    """字段/类别/评分/价位/坐标校验；非法条目丢弃。"""
    clat, clng = CITY_COORDS[city]
    out = []
    for p in pois:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name", "")).strip()
        category = p.get("category")
        if not name or category not in VALID_CATEGORIES:
            continue
        try:
            lat, lng = float(p["lat"]), float(p["lng"])
            rating = float(p["rating"])
            tier = int(p["price_tier"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (3.5 <= rating <= 5.0 and tier in VALID_TIERS):
            continue
        if abs(lat - clat) > 2.0 or abs(lng - clng) > 2.0:
            continue  # 坐标越界丢弃
        desc = str(p.get("description", "")).strip()
        if not desc:
            continue
        tags = [str(t) for t in (p.get("tags") or []) if str(t).strip()][:4]
        out.append({
            "poi_id": "", "city": city, "name": name, "category": category,
            "lat": lat, "lng": lng, "rating": rating, "price_tier": tier,
            "description": desc, "tags": tags,
        })
    return out


def default_corpus_path() -> Path:
    return Path(os.environ.get("POI_CORPUS_PATH", Path(__file__).resolve().parents[2] / "data" / "poi_corpus.jsonl"))


def main() -> int:
    provider = DeepSeekProvider(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
    )
    out_path = default_corpus_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with out_path.open("w", encoding="utf-8") as f:
        for city in CITIES:
            pois = generate_city(provider, city)
            for p in pois:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
            total += len(pois)
            print(f"{city}: {len(pois)} 条")
    print(f"完成：{total} 条 → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
