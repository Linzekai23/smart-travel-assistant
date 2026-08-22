"""test_retriever.py —— 三级粒度检索"""
from pathlib import Path

import pytest

from app.rag import retriever
from app.rag.ingest import load_corpus
from app.rag.vector_store import VectorStore

from conftest import FakeEmbedder

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pois.jsonl"


@pytest.fixture()
def store(tmp_path):
    s = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    s.upsert_pois(load_corpus(FIXTURE))
    retriever.set_store(s)
    yield s
    retriever.set_store(None)


def test_normalize_region_city():
    assert retriever.normalize_region("广州") == ("广东", "广州")
    assert retriever.normalize_region("guangzhou") == ("广东", "广州")
    assert retriever.normalize_region("成都") == ("四川", "成都")
    assert retriever.normalize_region("chengdu") == ("四川", "成都")


def test_normalize_region_province():
    assert retriever.normalize_region("广东") == ("广东", None)
    assert retriever.normalize_region("广东省") == ("广东", None)
    assert retriever.normalize_region("粤") == ("广东", None)
    assert retriever.normalize_region("guangdong") == ("广东", None)


def test_normalize_region_unknown():
    assert retriever.normalize_region("巴黎") == (None, None)
    assert retriever.normalize_region("") == (None, None)


def test_search_pois_in_kb_city(store):
    pois = retriever.search_pois("广州")
    assert {p["name"] for p in pois} == {"广州塔", "白云山"}


def test_search_pois_by_province(store):
    pois = retriever.search_pois("广东")
    assert {p["name"] for p in pois} == {"广州塔", "白云山", "丹霞山", "世界之窗"}
    assert len(pois) == 4


def test_search_pois_out_of_kb_city_falls_back_to_province(store):
    """搜库外城市（佛山）→ 所在省（广东）其他景点。"""
    pois = retriever.search_pois("佛山")
    assert {p["name"] for p in pois} == {"广州塔", "白云山", "丹霞山", "世界之窗"}


def test_search_pois_semantic_query(store):
    pois = retriever.search_pois("成都", query="老街")
    assert pois and pois[0]["name"] == "宽窄巷子"


def test_search_pois_unknown_region(store):
    assert retriever.search_pois("巴黎") == []


def test_get_poi(store):
    p = retriever.get_poi("beijing-001")
    assert p and p["name"] == "故宫博物院" and p["province"] == "北京"
    assert retriever.get_poi("nope") is None


def test_search_nearby(store):
    # 广州塔(23.1066, 113.3245) 周边 100km 内：广州塔自身（距离 0）+ 白云山；丹霞山(~250km) 被过滤
    nearby = retriever.search_nearby(23.1066, 113.3245, category="attraction", radius_km=100.0, k=5)
    assert {p["name"] for p in nearby} >= {"广州塔", "白云山"}
    assert "丹霞山" not in {p["name"] for p in nearby}


def test_get_store_without_set_raises(monkeypatch, tmp_path):
    """未 set_store 且模型目录不存在 → RuntimeError（不触发真实模型下载）。"""
    monkeypatch.setattr(retriever, "_store", None)
    monkeypatch.setattr("app.rag.download_model.default_model_dir", lambda: tmp_path / "no-model")
    with pytest.raises(RuntimeError, match="模型未就绪"):
        retriever.get_store()
