import math

import pytest

from conftest import FakeEmbedder, FakeProvider


def test_fake_embedder_dimension_and_norm():
    out = FakeEmbedder().embed(["你好"])
    assert len(out) == 1
    assert len(out[0]) == 512
    norm = math.sqrt(sum(x * x for x in out[0]))
    assert abs(norm - 1.0) < 1e-9


def test_fake_embedder_deterministic():
    e = FakeEmbedder()
    assert e.embed(["abc"]) == e.embed(["abc"])


def test_fake_embedder_similar_keyword_cosine():
    e = FakeEmbedder()
    doc_restaurant = e.embed(["成都 火锅 麻辣"])[0]
    doc_attraction = e.embed(["宽窄巷子 老街"])[0]
    query = e.embed_query("火锅")
    sim_restaurant = sum(a * b for a, b in zip(doc_restaurant, query))
    sim_attraction = sum(a * b for a, b in zip(doc_attraction, query))
    assert sim_restaurant > sim_attraction


def test_embedder_interface_shape():
    """真实 Embedder 的构造签名存在（不加载模型）。"""
    from app.rag.embeddings import Embedder, MODEL_ID

    assert Embedder.__init__.__code__.co_argcount == 2  # (self, model_path)
    assert MODEL_ID == "BAAI/bge-small-zh-v1.5"
    assert hasattr(Embedder, "embed_query")


def test_fake_provider_json_mode_records_once():
    """json_mode 调用只记录一次 calls（chat 委托 chat_json，不得双记录）。"""
    p = FakeProvider(
        json_responses={"景点": {"poi": "宽窄巷子"}},
        text_responses={"景点": "宽窄巷子"},
    )
    messages = [{"role": "user", "content": "推荐成都景点"}]

    p.chat(messages, json_mode=True)
    assert len(p.calls) == 1

    p.chat(messages)
    assert len(p.calls) == 2


def test_fake_provider_unmatched_raises():
    """未配置的 prompt 在 json_mode 与非 json_mode 两条路径都抛 AssertionError。"""
    p = FakeProvider(text_responses={"你好": "您好"})

    with pytest.raises(AssertionError):
        p.chat([{"role": "user", "content": "随便一段未配置的文本"}])

    with pytest.raises(AssertionError):
        p.chat([{"role": "user", "content": "随便一段未配置的文本"}], json_mode=True)
