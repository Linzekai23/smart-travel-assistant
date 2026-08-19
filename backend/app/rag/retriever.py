"""RAG 检索对外接口（Planner 依赖注入点）。

- search_pois：同城 + 类别过滤 + 语义检索（query 为空按 rating 降序）
- search_nearby："周边"检索 —— 同城 + haversine 距离排序（radius_km 内）
- get_store：惰性单例（CHROMA_PERSIST_DIR + 真实 BGE）；set_store 供测试注入
"""
from __future__ import annotations

import math

from app.rag.generate import CITY_EN
from app.rag.vector_store import VectorStore

# 城市别名（中文名 + 拼音，大小写不敏感）
_CITY_ALIASES: dict[str, str] = {c: c for c in CITY_EN}
_CITY_ALIASES.update({en: c for c, en in CITY_EN.items()})

_store: VectorStore | None = None


def set_store(store: VectorStore | None) -> None:
    """测试注入点：替换全局检索存储（FakeEmbedder 版）。"""
    global _store
    _store = store


def get_store() -> VectorStore:
    """惰性单例；首次调用创建（CHROMA_PERSIST_DIR + 真实 BGE）。

    模型未下载时抛 RuntimeError 提示先执行 `python -m app.rag.download_model`——
    不在服务进程内触发联网下载（避免请求挂起），下载是显式 CLI 步骤。
    """
    global _store
    if _store is None:
        from app.rag.download_model import default_model_dir
        from app.rag.embeddings import Embedder
        from app.rag.ingest import default_chroma_dir

        model_path = default_model_dir()
        if not (model_path.exists() and any(model_path.iterdir())):
            raise RuntimeError(
                f"BGE 模型未就绪：{model_path}。请先运行 python -m app.rag.download_model"
            )
        embedder = Embedder(str(model_path))
        _store = VectorStore(str(default_chroma_dir()), embedder)
    return _store


def normalize_city(name: str) -> str | None:
    """中文名/拼音归一为 CITY_EN 的城市名，无法识别返回 None。"""
    return _CITY_ALIASES.get(name.strip().lower())


def search_pois(
    city: str,
    *,
    category: str | None = None,
    query: str | None = None,
    k: int = 10,
) -> list[dict]:
    """同城检索；query 提供时语义排序，否则按 rating 降序。"""
    city = normalize_city(city)
    if city is None:
        return []
    return get_store().query(query or "", city=city, category=category, k=k)


def get_poi(poi_id: str) -> dict | None:
    """按 poi_id 取 POI；不存在返回 None。"""
    for p in get_store().get_all():
        if p["poi_id"] == poi_id:
            return p
    return None


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点球面距离（km）。"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def search_nearby(
    lat: float,
    lng: float,
    *,
    category: str | None = None,
    radius_km: float = 3.0,
    k: int = 5,
) -> list[dict]:
    """同城候选 + 距离过滤排序的"周边"检索（数据量小，全量计算即可）。"""
    candidates = [p for p in get_store().get_all(category=category) if p.get("lat") is not None]
    scored = []
    for p in candidates:
        d = _haversine(lat, lng, float(p["lat"]), float(p["lng"]))
        if d <= radius_km:
            scored.append((d, p))
    scored.sort(key=lambda item: item[0])
    return [p for _, p in scored[:k]]
