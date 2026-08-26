"""高德路线规划：geocode/路线解析 + 降级（全 mock，无网络）。"""
import pytest
from fastapi.testclient import TestClient

from app.api.amap_route import AmapRouteService
from app.main import app

GEOCODES_JSON = {
    "status": "1",
    "geocodes": [
        {"location": "104.0665,30.5728"},
        {"location": "bad-loc"},
    ],
}

TRANSIT_JSON = {
    "status": "1",
    "route": {
        "transits": [{
            "duration": "1500",
            "distance": "9000",
            "cost": "6",
            "segments": [
                {"bus": {"buslines": [{"name": "地铁1号线",
                                      "polyline": "104.0,30.5;104.1,30.6"}]}},
                {"bus": {"buslines": [{"name": "公交52路",
                                      "polyline": "104.1,30.6;104.2,30.7"},
                                      {"name": "地铁1号线"}]}},
                {"walking": {"polyline": "104.2,30.7;bad;104.3,30.8"}},
            ],
        }],
    },
}

DRIVING_JSON = {
    "status": "1",
    "route": {"paths": [{"duration": "600", "distance": "5000", "tolls": "10",
                         "steps": [{"polyline": "104.0,30.5;104.05,30.55"},
                                   {"polyline": "104.05,30.55;104.1,30.6"}]}]},
}

WALKING_JSON = {
    "status": "1",
    "route": {"paths": [{"duration": "1200", "distance": "1500",
                         "steps": [{"polyline": "104.0,30.5;104.02,30.52"}]}]},
}


class FakeResponse:
    def __init__(self, payload, status_code: int = 200, json_error=None) -> None:
        self._payload = payload
        self.status_code = status_code
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeHttp:
    def __init__(self, payload=None, status: int = 200, json_error=None) -> None:
        self._payload = payload
        self.status = status
        self._json_error = json_error
        self.calls: list[str] = []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        if self._payload is None:
            return None  # 模拟网络异常（http_get 返回 None → 下层处理）
        return FakeResponse(self._payload, self.status, self._json_error)


class Boom:
    def __call__(self, *a, **kw):
        raise TimeoutError("timeout")


@pytest.fixture(autouse=True)
def _amap_key(monkeypatch):
    monkeypatch.setenv("AMAP_KEY", "test-key-123")


@pytest.fixture(autouse=True)
def _no_real_provider(monkeypatch):
    """TestClient lifespan 强制走"未配置"分支：本机若配了 DEEPSEEK_API_KEY，
    真实 get_provider 会创建模块级单例，污染 test_deepseek.py 的无 key 断言。"""
    def _raise() -> None:
        raise RuntimeError("缺少环境变量 DEEPSEEK_API_KEY（DeepSeek 平台申请后配置）")
    monkeypatch.setattr("app.main.get_provider", _raise)


FROM = {"lat": 30.5728, "lng": 104.0665}
TO = {"lat": 30.6600, "lng": 104.0700}


# ---------------------------------------------------------------------------
# geocode
# ---------------------------------------------------------------------------


def test_geocode_parses_first_valid_location():
    http = FakeHttp(GEOCODES_JSON)
    assert AmapRouteService(http_get=http).geocode("成都", "天府广场") == {
        "lat": 30.5728, "lng": 104.0665}


def test_geocode_skips_bad_location_and_returns_second():
    payload = {"status": "1", "geocodes": [
        {"location": "bad"},
        {"location": "104.0000,30.0000"},
    ]}
    assert AmapRouteService(http_get=FakeHttp(payload)).geocode("成都", "x") == {
        "lat": 30.0, "lng": 104.0}


def test_geocode_no_key(monkeypatch):
    monkeypatch.delenv("AMAP_KEY")
    http = FakeHttp(GEOCODES_JSON)
    assert AmapRouteService(http_get=http).geocode("成都", "x") is None
    assert http.calls == []  # 无 key 不发请求


def test_geocode_failures_return_none():
    for http in [FakeHttp(None), FakeHttp({"status": "0"}),
                 FakeHttp("html", 200), FakeHttp({}, 500),
                 FakeHttp(json_error=ValueError("bad json")), Boom()]:
        assert AmapRouteService(http_get=http).geocode("成都", "x") is None


# ---------------------------------------------------------------------------
# route
# ---------------------------------------------------------------------------


def test_transit_parses():
    http = FakeHttp(TRANSIT_JSON)
    result = AmapRouteService(http_get=http).route(FROM, TO, "transit", "成都")
    assert result == {
        "duration_min": 25,      # 1500s → 25min
        "distance_km": 9.0,
        "cost_yuan": 6,
        "summary": "地铁1号线、公交52路",  # 去重 + 最多 2 条
        # 地铁段 polyline + 公交段 polyline（共享接点去重）+ 步行段（坏坐标跳过）
        "polyline": [[30.5, 104.0], [30.6, 104.1], [30.7, 104.2], [30.8, 104.3]],
    }


def test_transit_zero_cost_none():
    payload = {"status": "1", "route": {"transits": [{
        "duration": "60", "distance": "500", "cost": "0", "segments": []}]}}
    result = AmapRouteService(http_get=FakeHttp(payload)).route(FROM, TO)
    assert result["cost_yuan"] is None  # 0 元不显示
    assert result["summary"] is None    # 无公交线名
    assert result["polyline"] == []     # 无几何不崩


def test_transit_polyline_walking_only_segment():
    """纯步行段（无 buslines）→ 取 walking.polyline，不丢段。"""
    payload = {"status": "1", "route": {"transits": [{
        "duration": "60", "distance": "500", "cost": "0",
        "segments": [{"walking": {"polyline": "104.0,30.5;104.1,30.5"}}]}]}}
    result = AmapRouteService(http_get=FakeHttp(payload)).route(FROM, TO)
    assert result["polyline"] == [[30.5, 104.0], [30.5, 104.1]]


def test_driving_parses():
    result = AmapRouteService(http_get=FakeHttp(DRIVING_JSON)).route(FROM, TO, "driving")
    assert result == {"duration_min": 10, "distance_km": 5.0, "cost_yuan": 10,
                      "summary": None,
                      "polyline": [[30.5, 104.0], [30.55, 104.05], [30.6, 104.1]]}


def test_walking_parses():
    result = AmapRouteService(http_get=FakeHttp(WALKING_JSON)).route(FROM, TO, "walking")
    assert result == {"duration_min": 20, "distance_km": 1.5, "cost_yuan": None,
                      "summary": None,
                      "polyline": [[30.5, 104.0], [30.52, 104.02]]}


def test_route_no_steps_polyline_empty():
    """高德返回无 steps/segments 几何 → polyline []（前端画虚线直线），不崩。"""
    payload = {"status": "1", "route": {"paths": [{"duration": "60", "distance": "500"}]}}
    result = AmapRouteService(http_get=FakeHttp(payload)).route(FROM, TO, "driving")
    assert result["polyline"] == []


def test_parse_polyline_malformed_skips_bad_points():
    from app.api.amap_route import _parse_polyline
    assert _parse_polyline("104.0,30.5;bad;x,y;104.1,30.6") == [
        [30.5, 104.0], [30.6, 104.1]]
    assert _parse_polyline(None) == []
    assert _parse_polyline("") == []


def test_route_failures_return_none():
    for http in [FakeHttp(None), FakeHttp({"status": "0"}), FakeHttp({}, 500),
                 FakeHttp(json_error=ValueError()), Boom()]:
        assert AmapRouteService(http_get=http).route(FROM, TO) is None


def test_route_transit_fallback_to_driving():
    """transit 失败（无方案）→ 返回 None（调用方降级直线距离），不抛。"""
    payload = {"status": "1", "route": {"transits": []}}
    assert AmapRouteService(http_get=FakeHttp(payload)).route(FROM, TO) is None


# ---------------------------------------------------------------------------
# API 层
# ---------------------------------------------------------------------------


def _patch_service(monkeypatch, geocode=None, route=None):
    import app.api.amap_route as mod

    class Stub:
        def __init__(self, http_get=None):
            pass

        def geocode(self, city, name):
            return geocode

        def route(self, from_ll, to_ll, mode="transit", city=""):
            return route

    monkeypatch.setattr(mod, "AmapRouteService", Stub)


def test_api_route_success(monkeypatch):
    _patch_service(monkeypatch,
                   geocode={"lat": 30.0, "lng": 104.0},
                   route={"duration_min": 25, "distance_km": 9.0,
                          "cost_yuan": 6, "summary": "地铁1号线",
                          "polyline": [[30.0, 104.0], [30.1, 104.1]]})
    with TestClient(app) as c:
        resp = c.get("/api/route", params={"city": "成都", "from": "A", "to": "B"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True and data["source"] == "amap"
        assert data["duration_min"] == 25 and data["summary"] == "地铁1号线"
        # 前端地图用：起终点坐标 + 路线几何一并返回
        assert data["from_ll"] == {"lat": 30.0, "lng": 104.0}
        assert data["to_ll"] == {"lat": 30.0, "lng": 104.0}
        assert data["polyline"] == [[30.0, 104.0], [30.1, 104.1]]


def test_api_route_estimate_fallback(monkeypatch):
    _patch_service(monkeypatch,
                   geocode={"lat": 30.0, "lng": 104.0},
                   route=None)  # 路线失败 → 直线距离
    with TestClient(app) as c:
        resp = c.get("/api/route", params={"city": "成都", "from": "A", "to": "B"})
        data = resp.json()
        assert data["ok"] is True and data["source"] == "estimate"
        assert data["distance_km"] >= 0 and data["duration_min"] is None
        assert "仅供参考" in data["message"]


def test_api_route_no_key(monkeypatch):
    monkeypatch.delenv("AMAP_KEY")
    with TestClient(app) as c:
        resp = c.get("/api/route", params={"city": "成都", "from": "A", "to": "B"})
        assert resp.status_code == 200
        assert resp.json()["source"] == "no_key"


def test_api_route_geocode_fail(monkeypatch):
    _patch_service(monkeypatch, geocode=None)
    with TestClient(app) as c:
        resp = c.get("/api/route", params={"city": "成都", "from": "不存在的地方", "to": "B"})
        data = resp.json()
        assert data["ok"] is False and data["source"] == "geocode_fail"
        assert "不存在的地方" in data["message"]
