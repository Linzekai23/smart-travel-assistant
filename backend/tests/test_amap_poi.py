"""高德 POI 检索：解析/过滤/去重 + 降级（全 mock，无网络）。"""
import urllib.parse

import pytest

from app.api.amap_poi import AmapPoiService

POIS_JSON = {
    "status": "1", "count": "20",
    "pois": [
        {"id": "B0FFH1", "name": "马旺子·川小馆(太古里店)", "type": "餐饮服务;中餐厅",
         "location": "104.0825,30.6512", "address": "中纱帽街8号", "tel": "028-88888888",
         "photos": [{"url": "https://a.amap.com/p1.jpg"}, {"url": "https://a.amap.com/p2.jpg"}]},
        {"id": "B0FFH2", "name": "马旺子·川小馆(春熙路店)", "type": "餐饮服务;中餐厅",
         "location": "104.0811,30.6522", "address": "春熙路1号", "tel": "", "photos": []},
        {"id": "B0FFH3", "name": "云隐小院", "type": "住宿服务;民宿",
         "location": "104.1354,30.5869", "address": "幸福路46号", "tel": "15008405593",
         "photos": [{"url": "https://a.amap.com/h1.jpg"}]},
        {"id": "B0FFH4", "name": "坏坐标店", "type": "餐饮服务;中餐厅",
         "location": "", "address": "x", "tel": "", "photos": []},
    ],
}


class FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, payload=POIS_JSON, status: int = 200) -> None:
        self._payload = payload
        self.status = status
        self.calls: list[str] = []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        return FakeResponse(self._payload, self.status)


@pytest.fixture(autouse=True)
def _amap_key(monkeypatch):
    monkeypatch.setenv("AMAP_KEY", "test-key-123")


def test_restaurants_parse_and_filter(tmp_path):
    """只保留餐饮服务主分类；分店去重（太古里店先出现 → 保留它）；解析全部字段。"""
    http = FakeHttp()
    svc = AmapPoiService(http_get=http)
    out = svc.search_restaurants("成都")
    assert len(out) == 1
    item = out[0]
    assert item["poi_id"] == "amap-B0FFH1"          # amap- 前缀
    assert item["name"] == "马旺子·川小馆(太古里店)"   # 原名保留（去重的是去尾后）
    assert item["category"] == "restaurant"
    assert item["lat"] == 30.6512 and item["lng"] == 104.0825
    assert item["address"] == "中纱帽街8号"
    assert item["tel"] == "028-88888888"
    assert item["photo_url"] == "https://a.amap.com/p1.jpg"  # photos[0]
    # city 是 URL-encoded 中文；types 是 ASCII 原样
    assert urllib.parse.quote("成都") in http.calls[0] and "types=050000" in http.calls[0]


def test_hotels_keep_only_hotel_main_type(tmp_path):
    """美食结果里的住宿服务被过滤；酒店查询只保留住宿服务主分类。"""
    http = FakeHttp()
    svc = AmapPoiService(http_get=http)
    out = svc.search_hotels("成都")
    assert len(out) == 1
    assert out[0]["name"] == "云隐小院"              # 住宿服务被保留
    assert out[0]["category"] == "hotel"
    assert "types=100000" in http.calls[0]


def test_empty_tel_and_photos(tmp_path):
    """tel 空串 → None；photos 空 → photo_url None；无坐标条目丢弃。"""
    http = FakeHttp()
    svc = AmapPoiService(http_get=http)
    out = svc.search_restaurants("成都")
    assert out[0]["tel"] == "028-88888888"
    assert "坏坐标店" not in [i["name"] for i in out]


def test_no_key_returns_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("AMAP_KEY")
    svc = AmapPoiService(http_get=FakeHttp())
    assert svc.search_restaurants("成都") == []
    assert svc.search_hotels("成都") == []


def test_amap_error_status_returns_empty(tmp_path):
    http = FakeHttp(payload={"status": "0", "info": "USERKEY_PLAT_NOMATCH"}, status=200)
    svc = AmapPoiService(http_get=http)
    assert svc.search_restaurants("成都") == []


def test_http_failure_returns_empty(tmp_path):
    class Boom:
        def __call__(self, url, **kwargs):
            raise TimeoutError("timeout")

    svc = AmapPoiService(http_get=Boom())
    assert svc.search_restaurants("成都") == []


def test_dedup_drops_second_branch(tmp_path):
    """同一连锁分店去重：去掉 (xxx店) 后缀后相同 → 只留第一条。"""
    http = FakeHttp()
    svc = AmapPoiService(http_get=http)
    out = svc.search_restaurants("成都")
    assert [i["name"] for i in out] == ["马旺子·川小馆(太古里店)"]
