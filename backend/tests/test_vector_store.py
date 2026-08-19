from app.rag.vector_store import VectorStore

from conftest import FakeEmbedder


def _poi(i: int, city: str = "北京", category: str = "attraction", name: str = "景点", rating: float = 4.5, tags=None) -> dict:
    return {
        "poi_id": f"test-{i:03d}", "city": city, "name": name,
        "category": category, "rating": rating, "price_tier": 2,
        "lat": 39.9, "lng": 116.4, "description": f"第{i}个测试点",
        "tags": tags or ["测试"],
    }


def test_upsert_and_count(tmp_path):
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    assert store.count() == 0
    n = store.upsert_pois([_poi(1), _poi(2)])
    assert n == 2 and store.count() == 2
    # 重复 upsert 幂等（同一 poi_id 覆盖）
    store.upsert_pois([_poi(1)])
    assert store.count() == 2


def test_query_by_city_and_category(tmp_path):
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([
        _poi(1, city="北京", category="attraction", name="故宫博物院"),
        _poi(2, city="北京", category="restaurant", name="全聚德烤鸭"),
        _poi(3, city="成都", category="restaurant", name="蜀大侠火锅"),
    ])
    hits = store.query("故宫", city="北京", category="attraction", k=5)
    assert [p["poi_id"] for p in hits] == ["test-001"]
    hits2 = store.query("火锅", city="成都")
    assert hits2 and hits2[0]["poi_id"] == "test-003"


def test_query_empty_text_sorts_by_rating(tmp_path):
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([
        _poi(1, name="普通景点", rating=4.0),
        _poi(2, name="高分景点", rating=4.9),
    ])
    hits = store.query("", city="北京", category="attraction", k=5)
    assert hits[0]["poi_id"] == "test-002"  # rating 高者在前


def test_get_all_and_poi_shape(tmp_path):
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([_poi(1, tags=["历史", "免费"]), _poi(2, city="成都")])
    all_pois = store.get_all()
    assert len(all_pois) == 2
    first = all_pois[0]
    required = {"poi_id", "city", "name", "category", "rating",
                "price_tier", "lat", "lng", "description", "tags"}
    assert set(first) == required
    assert first["tags"] == ["历史", "免费"]  # tags 恢复为 list
    assert store.get_all(city="成都")[0]["poi_id"] == "test-002"
