"""高德 POI 检索：解析/过滤/去重 + 降级（全 mock，无网络）。"""
import io
import urllib.parse

import pytest

from app.api.amap_poi import (
    MIN_PHOTO_SCORE,
    AmapPoiService,
    _pick_best_photo,
    _score_photo,
)


def _jpeg(rgb: tuple[int, int, int]) -> bytes:
    """内存生成纯色 JPEG（照片评分测试用，无网络）。"""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), rgb).save(buf, "JPEG")
    return buf.getvalue()

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
    def __init__(self, payload, status_code: int = 200, json_error=None) -> None:
        self._payload = payload
        self.status_code = status_code
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeHttp:
    def __init__(self, payload=POIS_JSON, status: int = 200, json_error=None) -> None:
        self._payload = payload
        self.status = status
        self._json_error = json_error
        self.calls: list[str] = []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        return FakeResponse(self._payload, self.status, self._json_error)


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
    svc = AmapPoiService(http_get=http,
                         photo_picker=lambda urls: "https://a.amap.com/h1.jpg",
                         hotel_fallback=lambda city: None)
    out = svc.search_hotels("成都")
    assert len(out) == 1
    assert out[0]["name"] == "云隐小院"              # 住宿服务被保留
    assert out[0]["category"] == "hotel"
    assert "types=100000" in http.calls[0]


# ---------- 酒店照片择优（阳光指数） ----------

def test_score_photo_ranks_sunny_above_dark():
    """明亮暖色高分，昏黄/纯暗低分；非图片数据给最低分。"""
    sunny = _score_photo(_jpeg((255, 205, 120)))
    dingy = _score_photo(_jpeg((173, 169, 146)))
    dark = _score_photo(_jpeg((40, 40, 40)))
    assert sunny >= MIN_PHOTO_SCORE > dingy > dark
    assert _score_photo(b"not an image") < 0


def test_pick_best_photo_chooses_sunniest():
    """多张照片取阳光指数最高的一张（不取第一张）。"""
    fake = {"https://a.amap.com/dark.jpg": _jpeg((40, 40, 40)),
            "https://a.amap.com/sun.jpg": _jpeg((255, 205, 120))}
    assert _pick_best_photo(["https://a.amap.com/dark.jpg",
                             "https://a.amap.com/sun.jpg"], fetch=fake.get) == \
        "https://a.amap.com/sun.jpg"


def test_pick_best_photo_all_dark_returns_none():
    """全部照片低于阈值 → None（触发通用大堂图兜底）。"""
    fake = {"https://a.amap.com/dark.jpg": _jpeg((40, 40, 40))}
    assert _pick_best_photo(["https://a.amap.com/dark.jpg"], fetch=fake.get) is None


def test_pick_best_photo_fetch_failure_skipped():
    """下载失败的照片跳过，不影响其余照片择优。"""
    def fetch(url):
        return None if url == "bad" else _jpeg((255, 205, 120))

    assert _pick_best_photo(["bad", "good"], fetch=fetch) == "good"


def test_pick_best_photo_empty_urls():
    assert _pick_best_photo([], fetch=lambda u: None) is None


def test_hotel_photo_picked_and_no_fallback(tmp_path):
    """酒店照片择优命中 → 用真实照片，不调通用兜底。"""
    calls = []
    svc = AmapPoiService(http_get=FakeHttp(),
                         photo_picker=lambda urls: "https://a.amap.com/h1.jpg",
                         hotel_fallback=lambda city: calls.append(city) or "https://bing/lobby.jpg")
    out = svc.search_hotels("成都")
    assert out[0]["photo_url"] == "https://a.amap.com/h1.jpg"
    assert calls == []


def test_hotel_dark_photos_fall_back_to_lobby(tmp_path):
    """酒店照片全太暗 → photo_url 用通用大堂图，兜底收到城市名。"""
    calls = []
    svc = AmapPoiService(http_get=FakeHttp(),
                         photo_picker=lambda urls: None,
                         hotel_fallback=lambda city: calls.append(city) or "https://bing/lobby.jpg")
    out = svc.search_hotels("成都")
    assert out[0]["photo_url"] == "https://bing/lobby.jpg"
    assert calls == ["成都"]


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


def test_search_tolerates_non_json_payload(tmp_path):
    """200 但返回非 JSON（HTML 网关页/代理页）→ 返回 [] 而非抛异常。"""
    http = FakeHttp(json_error=ValueError("Expecting value: line 1 column 1"))
    svc = AmapPoiService(http_get=http)
    assert svc.search_restaurants("成都") == []


def test_bad_coord_first_does_not_poison_dedup(tmp_path):
    """首条分店坐标坏（非数值，跳过）→ 不毒化去重链，同链第二条仍保留。"""
    payload = {
        "status": "1",
        "pois": [
            {"id": "X1", "name": "观锦餐厅(天府新谷店)", "type": "餐饮服务;中餐厅",
             "location": "abc,def", "address": "x", "tel": "", "photos": []},
            {"id": "X2", "name": "观锦餐厅(春熙路店)", "type": "餐饮服务;中餐厅",
             "location": "104.08,30.65", "address": "春熙路", "tel": "", "photos": []},
        ],
    }
    http = FakeHttp(payload=payload)
    svc = AmapPoiService(http_get=http)
    out = svc.search_restaurants("成都")
    assert [i["name"] for i in out] == ["观锦餐厅(春熙路店)"]
    assert out[0]["lat"] == 30.65 and out[0]["lng"] == 104.08


def test_search_tolerates_non_dict_photos(tmp_path):
    """photos 元素非 dict → photo_url 为 None，条目不丢弃（不整轮失败）。"""
    payload = {
        "status": "1",
        "pois": [
            {"id": "B0FFH1", "name": "马旺子·川小馆(太古里店)", "type": "餐饮服务;中餐厅",
             "location": "104.0825,30.6512", "address": "中纱帽街8号",
             "tel": "028-88888888", "photos": ["https://a.amap.com/p1.jpg"]},
        ],
    }
    http = FakeHttp(payload=payload)
    svc = AmapPoiService(http_get=http)
    out = svc.search_restaurants("成都")
    assert len(out) == 1
    assert out[0]["name"] == "马旺子·川小馆(太古里店)"
    assert out[0]["photo_url"] is None


def test_fishing_venues_filtered_from_restaurants(tmp_path):
    """垂钓园等休闲场所混在餐饮服务里（如"丽江塘钓鱼"）→ 不进餐厅候选。"""
    payload = {
        "status": "1",
        "pois": [
            {"id": "F1", "name": "丽江塘钓鱼",
             "type": "餐饮服务;休闲餐饮场所|体育休闲服务;体育休闲服务场所",
             "location": "104.08,30.65", "address": "青城山", "tel": "", "photos": []},
            {"id": "F2", "name": "文化渔乐钓场", "type": "餐饮服务;中餐厅",
             "location": "104.08,30.65", "address": "x", "tel": "", "photos": []},
            {"id": "F3", "name": "十八里家常鱼庄", "type": "餐饮服务;中餐厅",
             "location": "104.08,30.65", "address": "x", "tel": "", "photos": []},
        ],
    }
    http = FakeHttp(payload=payload)
    svc = AmapPoiService(http_get=http)
    out = svc.search_restaurants("成都")
    assert [i["name"] for i in out] == ["十八里家常鱼庄"]   # 鱼庄是餐厅，保留


# ---------- 景点检索（110000 风景名胜 + 140100 科教文化服务） ----------

ATTRACTIONS_JSON = {
    "status": "1", "count": "20",
    "pois": [
        {"id": "B0FFA1", "name": "武侯祠", "type": "风景名胜;名胜古迹",
         "location": "104.0489,30.6461", "address": "武侯祠大街231号", "tel": "028-85552965",
         "photos": [{"url": "https://a.amap.com/a1.jpg"}, {"url": "https://a.amap.com/a2.jpg"}]},
        {"id": "B0FFA2", "name": "某咖啡馆", "type": "餐饮服务;咖啡厅",
         "location": "104.0600,30.6500", "address": "x", "tel": "", "photos": []},
        {"id": "B0FFA3", "name": "锦里古街", "type": "风景名胜;文物古迹",
         "location": "104.0490,30.6480", "address": "武侯祠大街", "tel": "",
         "photos": []},
    ],
}


def test_attractions_parse_and_filter():
    """只保留风景名胜主分类；照片取第一张（不走 photo_picker）；URL 带 types=110000+keywords=旅游。"""
    http = FakeHttp(payload=ATTRACTIONS_JSON)
    picker_calls = []

    svc = AmapPoiService(http_get=http, photo_picker=lambda urls: picker_calls.append(urls) or "x")
    out = svc.search_attractions("成都")
    assert [i["name"] for i in out] == ["武侯祠", "锦里古街"]  # 咖啡馆被主分类过滤
    item = out[0]
    assert item["poi_id"] == "amap-B0FFA1"
    assert item["category"] == "attraction"
    assert item["lat"] == 30.6461 and item["lng"] == 104.0489
    assert item["address"] == "武侯祠大街231号" and item["tel"] == "028-85552965"
    assert item["photo_url"] == "https://a.amap.com/a1.jpg"   # 第一张
    assert picker_calls == []                                  # 景点不择优
    # 首个请求：风景名胜 + keywords=旅游（知名景点浮出的关键，实测六城教科书级）
    assert "types=110000" in http.calls[0]
    assert f"keywords={urllib.parse.quote('旅游')}" in http.calls[0]
    assert urllib.parse.quote("成都") in http.calls[0]


def test_attractions_photo_is_first_not_picked():
    """多张照片时景点取第一张；photo_picker 不被调用（与酒店区分）。"""
    http = FakeHttp(payload=ATTRACTIONS_JSON)
    svc = AmapPoiService(http_get=http, photo_picker=lambda urls: "picked")
    out = svc.search_attractions("成都")
    assert out[0]["photo_url"] == "https://a.amap.com/a1.jpg"


def test_attractions_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("AMAP_KEY")
    http = FakeHttp(payload=ATTRACTIONS_JSON)
    svc = AmapPoiService(http_get=http)
    assert svc.search_attractions("成都") == []
    assert http.calls == []  # 无 key 不发请求


def test_attractions_status_fail_returns_empty():
    http = FakeHttp(payload={"status": "0", "info": "INVALID_USER_KEY"}, status=200)
    svc = AmapPoiService(http_get=http)
    assert svc.search_attractions("成都") == []


def test_attractions_multi_category_type_passes_filter():
    """多分类 type（购物服务|风景名胜）任一 | 分段命中主分类即保留（宽窄巷子景区回归）。"""
    payload = {
        "status": "1",
        "pois": [
            {"id": "M1", "name": "宽窄巷子景区",
             "type": "购物服务;特色商业街;特色商业街|风景名胜;风景名胜相关;旅游景点",
             "location": "104.059,30.669", "address": "宽窄巷子", "tel": "", "photos": []},
            {"id": "M2", "name": "纯购物街", "type": "购物服务;特色商业街;特色商业街",
             "location": "104.06,30.67", "address": "x", "tel": "", "photos": []},
        ],
    }
    http = FakeHttp(payload=payload)
    svc = AmapPoiService(http_get=http)
    out = svc.search_attractions("成都")
    assert [i["name"] for i in out] == ["宽窄巷子景区"]  # 第二分类命中保留；纯购物不保留


def test_attractions_merges_museums():
    """景点双类型：风景名胜 + 科教文化服务（博物馆）合并，poi_id 去重，风景名胜在前。"""
    scenic_payload = {"status": "1", "pois": [
        {"id": "S1", "name": "武侯祠", "type": "风景名胜;名胜古迹",
         "location": "104.05,30.65", "address": "x", "tel": "", "photos": []},
    ]}
    museum_payload = {"status": "1", "pois": [
        {"id": "M1", "name": "成都武侯祠博物馆", "type": "科教文化服务;博物馆;博物馆",
         "location": "104.049,30.646", "address": "武侯祠大街", "tel": "", "photos": []},
        {"id": "S1", "name": "武侯祠(重复id)", "type": "科教文化服务;博物馆;博物馆",
         "location": "104.05,30.65", "address": "x", "tel": "", "photos": []},
        {"id": "M2", "name": "四川博物院", "type": "科教文化服务;博物馆;博物馆",
         "location": "104.06,30.66", "address": "浣花溪", "tel": "", "photos": []},
    ]}

    class DispatchHttp:
        def __init__(self):
            self.calls: list[str] = []

        def __call__(self, url, **kwargs):
            self.calls.append(url)
            if "types=140100" in url:
                return FakeResponse(museum_payload)
            return FakeResponse(scenic_payload)

    http = DispatchHttp()
    svc = AmapPoiService(http_get=http)
    out = svc.search_attractions("成都")
    assert [i["name"] for i in out] == ["武侯祠", "成都武侯祠博物馆", "四川博物院"]
    assert [i["poi_id"] for i in out] == ["amap-S1", "amap-M1", "amap-M2"]  # 重复 id 去重
    assert "types=110000" in http.calls[0] and "types=140100" in http.calls[-1]
    assert all(i["category"] == "attraction" for i in out)


def test_attractions_keyword_enough_skips_fallback():
    """keywords=旅游 结果 ≥5 条 → 不发无关键词兜底请求（共 2 次调用：关键词+博物馆）。"""
    scenic_payload = {"status": "1", "pois": [
        {"id": f"S{i}", "name": f"景点{i}", "type": "风景名胜;风景名胜",
         "location": f"104.0{i},30.6{i}", "address": "x", "tel": "", "photos": []}
        for i in range(6)]}

    class DispatchHttp:
        def __init__(self):
            self.calls: list[str] = []

        def __call__(self, url, **kwargs):
            self.calls.append(url)
            if "types=140100" in url:
                return FakeResponse({"status": "1", "pois": []})
            return FakeResponse(scenic_payload)

    http = DispatchHttp()
    svc = AmapPoiService(http_get=http)
    out = svc.search_attractions("成都")
    assert len(out) == 6
    assert len(http.calls) == 2  # 关键词查询 + 博物馆查询，无兜底


def test_attractions_keyword_sparse_fills_fallback():
    """keywords=旅游 结果不足 5 条 → 无关键词兜底补足（按 poi_id 去重）。"""
    kw_payload = {"status": "1", "pois": [
        {"id": "K1", "name": "关键词景点", "type": "风景名胜;风景名胜",
         "location": "104.01,30.61", "address": "x", "tel": "", "photos": []}]}
    fb_payload = {"status": "1", "pois": [
        {"id": "F1", "name": "兜底景点A", "type": "风景名胜;风景名胜",
         "location": "104.02,30.62", "address": "x", "tel": "", "photos": []},
        {"id": "K1", "name": "关键词景点(重复)", "type": "风景名胜;风景名胜",
         "location": "104.01,30.61", "address": "x", "tel": "", "photos": []}]}

    class DispatchHttp:
        def __init__(self):
            self.calls: list[str] = []

        def __call__(self, url, **kwargs):
            self.calls.append(url)
            if "keywords=" in url:
                return FakeResponse(kw_payload)
            if "types=140100" in url:
                return FakeResponse({"status": "1", "pois": []})
            return FakeResponse(fb_payload)

    http = DispatchHttp()
    svc = AmapPoiService(http_get=http)
    out = svc.search_attractions("成都")
    assert [i["name"] for i in out] == ["关键词景点", "兜底景点A"]
    assert len(http.calls) == 3  # 关键词 + 兜底 + 博物馆
