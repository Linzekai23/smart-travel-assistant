"""POI 语料入库：读取 JSONL → 校验 → 生成 poi_id → 向量化 → 向量库 upsert。

用法：python -m app.rag.ingest
（前置：python -m app.rag.download_model 下载 BGE 模型）
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from app.rag.embeddings import Embedder
from app.rag.generate import default_corpus_path
from app.rag.province_cities import PROVINCES, city_coord
from app.rag.vector_store import VectorStore

VALID_CATEGORIES = {"attraction"}


def load_corpus(jsonl_path: str | Path) -> list[dict]:
    """读取语料 JSONL：校验（省份/城市/类别/坐标 ±2°）+ 生成 poi_id（{城市拼音}-{序号:03d}）。"""
    pois: list[dict] = []
    with Path(jsonl_path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                p = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(p, dict):
                continue
            province = p.get("province")
            city = p.get("city")
            if (
                province not in PROVINCES
                or city not in PROVINCES[province]["poi_cities"]
                or p.get("category") not in VALID_CATEGORIES
            ):
                continue
            try:
                lat, lng = float(p["lat"]), float(p["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            clat, clng = city_coord(province, city)
            if abs(lat - clat) > 2.0 or abs(lng - clng) > 2.0:
                continue  # 坐标越界丢弃（语料可能被手工编辑，二次校验）
            p["province"] = province
            p["city"] = city
            p["category"] = "attraction"
            pois.append(p)
    counts: dict[str, int] = {}
    for p in pois:
        key = p["city"]
        counts[key] = counts.get(key, 0) + 1
        p["poi_id"] = f"{PROVINCES[p['province']]['poi_cities'][key][0]}-{counts[key]:03d}"
    return pois


def run_ingest(jsonl_path: str | Path, store: VectorStore) -> int:
    """读取 + 入库，返回入库条数。"""
    pois = load_corpus(jsonl_path)
    return store.upsert_pois(pois)


def default_chroma_dir() -> Path:
    return Path(os.environ.get("CHROMA_PERSIST_DIR", Path(__file__).resolve().parents[2] / "data" / "chroma"))


def main() -> int:
    from app.rag.download_model import ensure_model, default_model_dir

    model_path = ensure_model(default_model_dir())
    print(f"加载 BGE: {model_path}")
    embedder = Embedder(model_path)
    store = VectorStore(str(default_chroma_dir()), embedder)
    corpus = default_corpus_path()
    n = run_ingest(str(corpus), store)
    print(f"入库完成：{n} 条，库内总数 {store.count()} → {default_chroma_dir()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
