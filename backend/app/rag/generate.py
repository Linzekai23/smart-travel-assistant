"""POI 语料生成：DeepSeek 按省份模板批量生成（一次一省，JSON 模式）。

产物是 backend/data/poi_corpus.jsonl，数据为 **AI 生成示例数据，
坐标仅供参考**（README 与前端展示均注明）。只生成景点（attraction）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from app.llm.deepseek import DeepSeekProvider
from app.rag.province_cities import PROVINCES, city_coord

# 34 省遍历顺序（语料生成与断言基准）
PROVINCE_ORDER = [
    "北京", "上海", "天津", "重庆",
    "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东",
    "广西", "海南", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
    "台湾", "香港", "澳门",
]

# 城市 → 拼音（全部 poi_cities 城市，动态生成；poi_id 与别名表共用）
CITY_EN: dict[str, str] = {
    city: pinyin
    for d in PROVINCES.values()
    for city, (pinyin, _coord) in d["poi_cities"].items()
}

VALID_TIERS = {1, 2, 3, 4}

GENERATE_SYSTEM_PROMPT = """你是中国旅游 POI 数据生成器。为指定省份生成著名旅游景点条目（AI 生成示例数据，坐标仅供参考，要落在对应城市市中心周边合理范围）。
只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{"province": "省份名", "pois": [
  {"name": "中文名", "city": "景点所在城市（必须是给定城市清单中的城市）",
   "lat": 纬度, "lng": 经度, "rating": 3.5到5.0一位小数,
   "price_tier": 1到4整数（门票价位）, "description": "50字以内，真实、信息密度高",
   "tags": ["2-4个标签，如 历史/夜景/亲子/自然/世界遗产"]}
]}
数量要求：共 4-6 个景点，分布在给定城市清单中（每城 1-3 个）。只生成景点，不要餐厅/酒店。"""


def generate_province(provider: DeepSeekProvider, province: str) -> list[dict]:
    """调用一次 DeepSeek 生成一省景点，返回校验后的条目（含 province/city 字段）。"""
    poi_cities = PROVINCES[province]["poi_cities"]
    cities_text = "、".join(poi_cities)
    messages = [
        {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"请为「{province}」生成著名景点数据。可选城市：{cities_text}（每城 1-3 个）。"
            f"城市中心坐标：{json.dumps({c: c2 for c, (_p, c2) in poi_cities.items()}, ensure_ascii=False)}。"
            "所有条目坐标必须在对应城市中心 ±2 度范围内。只输出 JSON。"
        )},
    ]
    raw = provider.chat_json(messages)
    pois = (raw.get("pois") or []) if isinstance(raw, dict) else []
    return validate_pois(province, pois)


def validate_pois(province: str, pois: list[dict]) -> list[dict]:
    """字段/城市/类别/评分/价位/坐标校验；非法条目丢弃。"""
    poi_cities = PROVINCES[province]["poi_cities"]
    out = []
    for p in pois:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name", "")).strip()
        city = str(p.get("city", "")).strip()
        if not name or city not in poi_cities:
            continue  # 城市必须在本省 poi_cities 内
        if p.get("category", "attraction") != "attraction":
            continue  # 语料只存景点
        try:
            lat, lng = float(p["lat"]), float(p["lng"])
            rating = float(p["rating"])
            tier = int(p["price_tier"])
        except (KeyError, TypeError, ValueError):
            continue
        clat, clng = city_coord(province, city)
        if not (3.5 <= rating <= 5.0 and tier in VALID_TIERS):
            continue
        if abs(lat - clat) > 2.0 or abs(lng - clng) > 2.0:
            continue  # 坐标越界丢弃
        desc = str(p.get("description") or "").strip()
        if not desc:
            continue
        tags_raw = p.get("tags") or []
        if isinstance(tags_raw, str):
            tags_raw = [tags_raw]
        tags = [str(t).strip() for t in tags_raw if str(t).strip()][:4]
        out.append({
            "poi_id": "", "province": province, "city": city, "name": name,
            "category": "attraction", "lat": lat, "lng": lng, "rating": rating,
            "price_tier": tier, "description": desc, "tags": tags,
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
        for province in PROVINCE_ORDER:
            pois = generate_province(provider, province)
            for p in pois:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
            total += len(pois)
            print(f"{province}: {len(pois)} 条")
    print(f"完成：{total} 条 → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
