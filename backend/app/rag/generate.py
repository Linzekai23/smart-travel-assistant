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
   "price_tier": 1到4整数（门票价位）, "description": "200-280字具体介绍：历史沿革、主要看点（具体点位/分区/建筑，不要'适合打卡'式套话）、门票价格与开放时间、建议游玩时长、交通提示，信息密度高",
   "tags": ["2-4个标签，如 历史/夜景/亲子/自然/世界遗产"]}
]}
数量要求：共 6-9 个景点，分布在给定城市清单中（省会/旅游大城市 2-4 个，其他城市 1-2 个）。只生成景点，不要餐厅/酒店。
如果用户消息中提供了"已有景点"清单，必须生成清单之外的景点（避免重复条目）。"""


def generate_province(provider: DeepSeekProvider, province: str,
                      *, existing: set[tuple[str, str]] | None = None) -> list[dict]:
    """调用一次 DeepSeek 生成一省景点，返回校验后的条目（含 province/city 字段）。

    existing：本省已有 (city, name) 集合（增量追加时传入）→ 提示 LLM 避开，降低重复。
    """
    poi_cities = PROVINCES[province]["poi_cities"]
    cities_text = "、".join(poi_cities)
    existing_text = ""
    if existing:
        names = sorted(f"{c}·{n}" for c, n in existing if c in poi_cities)
        if names:
            existing_text = (f"\n本省已有景点（不要重复生成这些）："
                             f"{'、'.join(names[:60])}" + ("等" if len(names) > 60 else "") + "。")
    messages = [
        {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"请为「{province}」生成著名景点数据。可选城市：{cities_text}（每城 1-3 个）。"
            f"城市中心坐标：{json.dumps({c: c2 for c, (_p, c2) in poi_cities.items()}, ensure_ascii=False)}。"
            f"所有条目坐标必须在对应城市中心 ±2 度范围内。只输出 JSON。{existing_text}"
        )},
    ]
    raw = provider.chat_json(messages)
    pois = (raw.get("pois") or []) if isinstance(raw, dict) else []
    return validate_pois(province, pois)


def merge_unique(pois: list[dict], existing: set[tuple[str, str]]) -> list[dict]:
    """过滤与 existing 重复的条目（按 (city, name)），返回新增列表并更新 existing。

    多轮生成累积用：每轮产物先过查重，重复的丢弃，不污染语料（同城同名才判重，
    不同城市同名景点如 中山公园 是多地真实存在的，允许共存）。
    """
    added = []
    for p in pois:
        key = (p.get("city"), p.get("name"))
        if not all(key) or key in existing:
            continue
        existing.add(key)
        added.append(p)
    return added


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


def _read_existing(jsonl_path: Path) -> set[tuple[str, str]]:
    """已有语料的 (city, name) 集合（增量追加去重基准；损坏行跳过）。"""
    if not jsonl_path.exists():
        return set()
    out: set[tuple[str, str]] = set()
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            p = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(p, dict) and p.get("city") and p.get("name"):
            out.add((str(p["city"]), str(p["name"])))
    return out


_LLM_RETRYABLE = (AssertionError, ValueError, KeyError, TypeError, RuntimeError)


def _generate_province_rounds(provider: DeepSeekProvider, province: str,
                              existing: set[tuple[str, str]], rounds: int) -> list[dict]:
    """一省生成 rounds 轮：单次调用失败（DeepSeek 长输出偶发截断 JSON）→ 同轮重试 3 次；
    每轮产物经 merge_unique 去重（existing 按省传入，各省互不干扰，可并行）。"""
    added: list[dict] = []
    for _ in range(rounds):
        pois: list[dict] = []
        for attempt in range(3):
            try:
                pois = generate_province(provider, province, existing=existing)
                break
            except _LLM_RETRYABLE:
                print(f"  {province} 第 {attempt + 1} 次调用失败，重试…", flush=True)
        added += merge_unique(pois, existing)
    return added


def main() -> int:
    import argparse
    from concurrent.futures import ThreadPoolExecutor, as_completed

    ap = argparse.ArgumentParser(description="POI 语料生成（追加模式：保留现有，多轮累积去重）")
    ap.add_argument("--rounds", type=int, default=1,
                    help="每省生成轮数（1=全量初始生成；2-3=增量扩量，推荐 3）")
    ap.add_argument("--start-province", type=str, default=None,
                    help="从指定省份继续（追加中途失败后续跑：--start-province 河北）")
    args = ap.parse_args()

    provider = DeepSeekProvider(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
    )
    start_idx = PROVINCE_ORDER.index(args.start_province) if args.start_province else 0
    out_path = default_corpus_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_existing(out_path)
    print(f"已有语料 {len(existing)} 条（同城同名去重基准），每省 {args.rounds} 轮追加…")
    # 各省独立生成 → 4 路并行（DeepSeek 无严格限流；写入回到主线程，无锁安全）
    total = 0
    with out_path.open("a", encoding="utf-8") as f:
        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = {
                ex.submit(_generate_province_rounds, provider, p,
                          {k for k in existing if k[0] in PROVINCES[p]["poi_cities"]},
                          args.rounds): p
                for p in PROVINCE_ORDER[start_idx:]
            }
            for fut in as_completed(futures):
                province = futures[fut]
                before = len([k for k in existing if k[0] in PROVINCES[province]["poi_cities"]])
                got = 0
                for p in fut.result():
                    key = (p["city"], p["name"])
                    if key in existing:
                        continue
                    existing.add(key)
                    f.write(json.dumps(p, ensure_ascii=False) + "\n")
                    got += 1
                total += got
                print(f"{province}: +{got} 条（已有 {before}）", flush=True)
    print(f"完成：新增 {total} 条，总量 {len(existing)} 条 → {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
