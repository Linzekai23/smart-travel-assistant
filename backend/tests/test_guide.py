"""攻略浏览 API：语料过滤 + 高德复用 + 降级（全 mock，无网络）。"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app

CORPUS_LINES = [
    {"province": "北京", "city": "北京", "name": "故宫博物院", "category": "attraction",
     "lat": 39.9, "lng": 116.4, "rating": 4.8, "price_tier": 2,
     "description": "故宫简介", "tags": ["历史"]},
    {"province": "北京", "city": "北京", "name": "颐和园", "category": "attraction",
     "lat": 40.0, "lng": 116.3, "rating": 4.7, "price_tier": 2,
     "description": "颐和园简介", "tags": ["园林"]},
    {"province": "四川", "city": "成都", "name": "宽窄巷子", "category": "attraction",
     "lat": 30.6, "lng": 104.0, "rating": 4.5, "price_tier": 1,
     "description": "宽窄巷子简介", "tags": ["老街"]},
    {"province": "四川", "city": "成都", "name": "坏数据行", "category": "attraction",
     "lat": None, "lng": None, "rating": "not-a-number", "price_tier": None,
     "description": "", "tags": []},
]


@pytest.fixture(autouse=True)
def _no_real_provider(monkeypatch):
    def _raise() -> None:
        raise RuntimeError("缺少环境变量 DEEPSEEK_API_KEY（DeepSeek 平台申请后配置）")
    monkeypatch.setattr("app.main.get_provider", _raise)


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAVEL_DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    yield


@pytest.fixture()
def _corpus(tmp_path, monkeypatch):
    from app.api import guide

    path = tmp_path / "corpus.jsonl"
    path.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in CORPUS_LINES),
        encoding="utf-8",
    )
    monkeypatch.setenv("POI_CORPUS_PATH", str(path))
    guide._load_corpus.cache_clear()  # lru_cache 跨测试共享，换路径必须清缓存
    yield
    guide._load_corpus.cache_clear()


@pytest.fixture(autouse=True)
def _amap_key(monkeypatch):
    monkeypatch.setenv("AMAP_KEY", "test-key-123")


@pytest.fixture(autouse=True)
def _fake_amap(monkeypatch):
    """guide 复用 AmapPoiService——monkeypatch 掉其两个检索方法（全 mock 无网络）。"""
    from app.api import guide

    class FakeAmap:
        def _no_key(self) -> bool:
            # 与真实 AmapPoiService 一致：无 AMAP_KEY → 返回空列表
            return not os.environ.get("AMAP_KEY")

        def search_attractions(self, city):
            if self._no_key():
                return []
            return [{"poi_id": "amap-a1", "name": "成都塔", "category": "attraction",
                     "lat": 30.64, "lng": 104.05, "address": "锦江区",
                     "tel": "028-1234567", "photo_url": "https://amap.example/a1.jpg"}] \
                if city == "成都" else []

        def search_restaurants(self, city):
            if self._no_key():
                return []
            return [{"poi_id": "amap-r1", "name": f"{city}火锅", "category": "restaurant",
                     "lat": 30.0, "lng": 104.0}] if city == "成都" else []

        def search_hotels(self, city):
            if self._no_key():
                return []
            return [{"poi_id": "amap-h1", "name": f"{city}酒店", "category": "hotel",
                     "lat": 30.1, "lng": 104.1}] if city == "成都" else []

    monkeypatch.setattr(guide, "amap_poi_service", FakeAmap())


def test_cities_list_from_province_registry(tmp_db, _corpus):
    """城市清单 = 全国地级市全清单（与语料无关）：含语料城市与非语料城市。"""
    with TestClient(app) as c:
        resp = c.get("/api/guide/cities")
        assert resp.status_code == 200
        cities = resp.json()["cities"]
        assert {"province": "北京", "city": "北京"} in cities
        assert {"province": "四川", "city": "成都"} in cities
        assert {"province": "广东", "city": "佛山"} in cities   # 语料外城市也可选
        assert {"province": "广东", "city": "江门"} in cities   # 新增地级市
        assert {"province": "河北", "city": "廊坊"} in cities
        assert len(cities) > 200  # 全国地级市规模，非语料城市数
        provinces = {x["province"] for x in cities}
        assert len(provinces) == 34  # 覆盖 34 省级行政区


def test_guide_amap_attractions_priority(tmp_db, _corpus):
    """高德真实景点优先：成都返回 amap- 景点（带地址/电话/照片直链），语料景点被覆盖。"""
    with TestClient(app) as c:
        data = c.get("/api/guide", params={"city": "成都"}).json()
    assert [a["name"] for a in data["attractions"]] == ["成都塔"]  # 非语料的宽窄巷子
    assert data["attractions"][0]["address"] == "锦江区"
    assert data["attractions"][0]["tel"] == "028-1234567"
    assert data["attractions"][0]["photo_url"] == "https://amap.example/a1.jpg"
    assert data["amap_available"] is True


def test_guide_attractions_filter_by_city(tmp_db, _corpus):
    """高德无结果（北京无真实 POI 配置）→ 语料兜底（故宫/颐和园），行为与改造前一致。"""
    with TestClient(app) as c:
        resp = c.get("/api/guide", params={"city": "北京"})
        assert resp.status_code == 200
        data = resp.json()
        assert [a["name"] for a in data["attractions"]] == ["故宫博物院", "颐和园"]
        assert data["amap_available"] is True


def test_guide_restaurants_hotels_from_amap(tmp_db, _corpus):
    with TestClient(app) as c:
        data = c.get("/api/guide", params={"city": "成都"}).json()
        assert data["restaurants"][0]["name"] == "成都火锅"
        assert data["hotels"][0]["name"] == "成都酒店"
        # 北京没配高德结果 → 空列表（不报错）
        data = c.get("/api/guide", params={"city": "北京"}).json()
        assert data["restaurants"] == [] and data["hotels"] == []


def test_guide_unknown_city_empty(tmp_db, _corpus):
    with TestClient(app) as c:
        data = c.get("/api/guide", params={"city": "不存在城市"}).json()
        assert data["attractions"] == [] and data["restaurants"] == []


def test_guide_no_amap_key(tmp_db, _corpus, monkeypatch):
    monkeypatch.delenv("AMAP_KEY")
    with TestClient(app) as c:
        data = c.get("/api/guide", params={"city": "成都"}).json()
        assert data["amap_available"] is False
        assert data["attractions"]  # 景点照常（语料）
        assert data["restaurants"] == [] and data["hotels"] == []


def test_guide_missing_corpus_file(tmp_db, tmp_path, monkeypatch):
    """语料文件缺失：城市清单照常（来自省级注册表），景点为空（无 key 无兜底）。"""
    monkeypatch.setenv("POI_CORPUS_PATH", str(tmp_path / "nope.jsonl"))
    monkeypatch.delenv("AMAP_KEY")
    with TestClient(app) as c:
        assert c.get("/api/guide", params={"city": "北京"}).status_code == 200
        assert c.get("/api/guide", params={"city": "北京"}).json()["attractions"] == []
        assert c.get("/api/guide/cities").json()["cities"]  # 城市清单不依赖语料
