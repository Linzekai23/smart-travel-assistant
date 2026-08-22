"""Chroma 向量库封装。

- 存储：PersistentClient（backend/data/chroma，TRAVEL_DB 同款 env 可覆盖）
- 集合：poi_kb，cosine 空间，自定义 embedding_function（注入 Embedder/FakeEmbedder）
- 文档文本：name + description + tags + category + province + city 聚合（检索语义的来源）
- metadata：{poi_id, province, city, name, category, rating, price_tier, lat, lng,
  description, tags_str}（tags 以逗号拼接，返回时还原为 list）
"""
from __future__ import annotations

from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb import PersistentClient

COLLECTION_NAME = "poi_kb"


class _BgeEmbeddingFunction(EmbeddingFunction):
    """把外部 embedder 适配为 Chroma 的 EmbeddingFunction 协议。"""

    def __init__(self, embedder) -> None:
        self._embedder = embedder

    def __call__(self, input: Documents) -> Embeddings:
        return self._embedder.embed(list(input))


def _doc_text(p: dict) -> str:
    tags = "、".join(p.get("tags", []))
    return (f"{p['name']}。{p.get('description', '')}。标签：{tags}。"
            f"类别：{p['category']}。省份：{p.get('province', '')}。城市：{p['city']}")


def _meta(p: dict) -> dict:
    return {
        "poi_id": p["poi_id"], "province": p.get("province", ""), "city": p["city"],
        "name": p["name"], "category": p["category"], "rating": float(p["rating"]),
        "price_tier": int(p["price_tier"]), "lat": float(p["lat"]),
        "lng": float(p["lng"]), "description": p.get("description", ""),
        "tags_str": ",".join(p.get("tags", [])),
    }


def _poi_dict(meta: dict) -> dict:
    d = {k: meta[k] for k in
         ("poi_id", "city", "name", "category", "rating",
          "price_tier", "lat", "lng", "description")}
    d["province"] = meta.get("province", "")
    d["tags"] = meta["tags_str"].split(",") if meta.get("tags_str") else []
    return d


class VectorStore:
    def __init__(self, persist_dir: str, embedder) -> None:
        self._client = PersistentClient(path=persist_dir)
        self._col = self._client.get_or_create_collection(
            COLLECTION_NAME,
            embedding_function=_BgeEmbeddingFunction(embedder),
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_pois(self, pois: list[dict]) -> int:
        """幂等入库：同一 poi_id 覆盖；返回条数。"""
        if not pois:
            return 0
        self._col.upsert(
            ids=[p["poi_id"] for p in pois],
            documents=[_doc_text(p) for p in pois],
            metadatas=[_meta(p) for p in pois],
        )
        return len(pois)

    def query(
        self,
        text: str,
        *,
        city: str | None = None,
        province: str | None = None,
        category: str | None = None,
        k: int = 10,
    ) -> list[dict]:
        """向量检索；text 为空时退化为 metadata 过滤 + rating 降序。"""
        where = self._where(city, province, category)
        if text.strip():
            result = self._col.query(query_texts=[text], where=where, n_results=k)
        else:
            fetched = self._col.get(where=where, limit=1000)
            metas = fetched.get("metadatas") or []
            metas = sorted(metas, key=lambda m: m.get("rating", 0), reverse=True)
            return [_poi_dict(m) for m in metas[:k]]
        return [_poi_dict(m) for m in (result.get("metadatas") or [[]])[0]]

    def get_all(
        self,
        city: str | None = None,
        province: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        fetched = self._col.get(where=self._where(city, province, category), limit=1000)
        return [_poi_dict(m) for m in (fetched.get("metadatas") or [])]

    def count(self) -> int:
        return self._col.count()

    @staticmethod
    def _where(
        city: str | None = None,
        province: str | None = None,
        category: str | None = None,
    ) -> dict | None:
        conds = []
        if province:
            conds.append({"province": province})
        if city:
            conds.append({"city": city})
        if category:
            conds.append({"category": category})
        if not conds:
            return None
        return conds[0] if len(conds) == 1 else {"$and": conds}
