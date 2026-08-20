from app.rag.ingest import load_corpus, run_ingest
from app.rag.vector_store import VectorStore

from conftest import FakeEmbedder

CORPUS_LINES = [
    '{"name": "宽窄巷子", "province": "四川", "city": "成都", "category": "attraction", "lat": 30.67, "lng": 104.06, "rating": 4.6, "price_tier": 1, "description": "老成都街区。", "tags": ["老街"]}',
    '{"name": "峨眉山", "province": "四川", "city": "乐山", "category": "attraction", "lat": 29.55, "lng": 103.77, "rating": 4.8, "price_tier": 2, "description": "佛教名山。", "tags": ["自然"]}',
    '{"name": "蜀大侠火锅", "province": "四川", "city": "成都", "category": "restaurant", "lat": 30.66, "lng": 104.07, "rating": 4.5, "price_tier": 3, "description": "火锅。", "tags": ["火锅"]}',
    '{"name": "坐标越界", "province": "四川", "city": "成都", "category": "attraction", "lat": 45.0, "lng": 120.0, "rating": 4.0, "price_tier": 1, "description": "越界。", "tags": []}',
]


def test_load_corpus_generates_poi_ids(tmp_path):
    p = tmp_path / "corpus.jsonl"
    p.write_text("\n".join(CORPUS_LINES), encoding="utf-8")
    pois = load_corpus(str(p))
    assert len(pois) == 2  # 餐厅类别与越界坐标被校验丢弃
    assert pois[0]["poi_id"] == "chengdu-001"
    assert pois[1]["poi_id"] == "leshan-001"


def test_load_corpus_drops_unknown_province(tmp_path):
    p = tmp_path / "corpus.jsonl"
    p.write_text('{"name": "x", "province": "巴黎", "city": "巴黎", "category": "attraction", "lat": 30.0, "lng": 104.0, "rating": 4.0, "price_tier": 1, "description": "x", "tags": []}',
                 encoding="utf-8")
    assert load_corpus(str(p)) == []


def test_run_ingest_upserts(tmp_path):
    p = tmp_path / "corpus.jsonl"
    p.write_text("\n".join(CORPUS_LINES), encoding="utf-8")
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    n = run_ingest(str(p), store)
    assert n == 2
    assert store.count() == 2
