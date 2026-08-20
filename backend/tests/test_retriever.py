import math
from pathlib import Path

import pytest

from app.rag import retriever
from app.rag.ingest import load_corpus
from app.rag.vector_store import VectorStore

from conftest import FakeEmbedder

pytestmark = pytest.mark.skip(reason="Task 3 重写")

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pois.jsonl"


@pytest.fixture()
def store(tmp_path):
    s = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    s.upsert_pois(load_corpus(FIXTURE))
    retriever.set_store(s)
    yield s
    retriever.set_store(None)


def test_normalize_city_aliases():
    assert retriever.normalize_city("北京") == "北京"
    assert retriever.normalize_city("beijing") == "北京"
    assert retriever.normalize_city("BeiJing") == "北京"
    assert retriever.normalize_city("成都") == "成都"
    assert retriever.normalize_city("chengdu") == "成都"
    assert retriever.normalize_city("巴黎") is None


def test_search_pois_by_category(store):
    pois = retriever.search_pois("北京", category="restaurant")
    assert {p["name"] for p in pois} == {"全聚德烤鸭（前门店）", "四季民福烤鸭店（故宫店）"}


def test_search_pois_semantic_query(store):
    pois = retriever.search_pois("成都", query="火锅")
    assert pois and pois[0]["name"].startswith("蜀大侠火锅")


def test_search_pois_unknown_city(store):
    assert retriever.search_pois("巴黎") == []


def test_get_poi(store):
    p = retriever.get_poi("beijing-001")
    assert p and p["name"] == "故宫博物院"
    assert retriever.get_poi("nope") is None


def test_search_nearby_radius_and_sort(store):
    # 故宫(39.9163, 116.3972) 周边 3km：四季民福(39.9180, 116.4000) 近，全聚德(39.8997, 116.3967) 远
    nearby = retriever.search_nearby(39.9163, 116.3972, category="restaurant", radius_km=3.0, k=5)
    assert nearby[0]["name"] == "四季民福烤鸭店（故宫店）"
    dist = retriever._haversine(39.9163, 116.3972, 39.9180, 116.4000)
    assert 0 < dist < 3.0


def test_get_store_without_set_raises(monkeypatch, tmp_path):
    # 模型目录与 chroma 目录都指到不存在的位置：get_store 必须在加载模型
    # 之前快速失败（模型不存在 → RuntimeError），而不是尝试联网下载挂起
    monkeypatch.setenv("RAG_MODEL_DIR", str(tmp_path / "no-model"))
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "no-chroma"))
    with pytest.raises(RuntimeError, match="模型未就绪"):
        retriever.get_store()
