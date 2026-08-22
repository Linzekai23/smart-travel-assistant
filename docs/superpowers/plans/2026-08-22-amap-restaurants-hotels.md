# 真实餐厅/酒店接入（高德 POI）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 行程中的餐厅/酒店从 LLM 编造的"（示例）"数据升级为高德地图真实商家（地址/电话/坐标/照片），地图打点区分三类。

**Architecture:** 新增 `amap_poi` 检索模块（v3 place/text，extensions=all 才有照片），planner 按城市查美食/酒店候选并入候选列表，LLM 引用 `amap-{id}` 前缀的 poi_id，enrich 附真实字段；无 key/失败返回 `[]` → 现有"（示例）"模式不变。

**Tech Stack:** Python requests + FastAPI（后端）；React + antd + Leaflet（前端）。

**Spec:** [docs/superpowers/specs/2026-08-22-amap-restaurants-hotels-design.md](../specs/2026-08-22-amap-restaurants-hotels-design.md)

## Global Constraints

- 高德 key 只从环境变量 `AMAP_KEY` 读（`backend/.env` 已建好并 gitignored）；绝不打印、绝不写入代码/提交
- 测试全 mock（FakeProvider/FakeHttp/monkeypatch），无网络、无真实 key 依赖
- 地图瓦片模板、subdomains、maxZoom、attribution、免责声明文案与 `z-[1000]` 逐字保留
- 高德实测：rating/price 不返回（不显示评分）；photos 100% 有（餐厅/酒店照片直接用高德直链）
- 景点数据保持 RAG 语料体系，不接高德
- 降级路径：无 key/高德异常 → 候选为空 → LLM 照旧编"（示例）"条目，现有行为不变
- 餐厅/酒店候选去重：name 去掉分店后缀（`(xxx店)`）后相同者只留第一条
- 美食/酒店结果过滤：type 主分类必须 `餐饮服务` / `住宿服务`（裸搜会混入其他分类）
- 所有 commit 以 `Co-Authored-By: Claude <noreply@anthropic.com>` 结尾
- 后端测试命令：`cd /d/agent/backend && .venv/Scripts/python -m pytest`；前端门禁：`cd /d/agent/frontend && npm run build && npm run lint`

---

### Task 1: amap_poi 模块（高德 POI 检索）

**Files:**
- Create: `backend/app/api/amap_poi.py`
- Modify: `backend/app/main.py`（注册路由）
- Create: `backend/tests/test_amap_poi.py`

**Interfaces:**
- Produces: `AmapPoiService`（`search_restaurants(city) -> list[dict]`、`search_hotels(city) -> list[dict]`）、模块级 `service`、`router`（`GET /api/amap-poi?city=&type=`）。返回条目字段：`poi_id`（`amap-{id}` 前缀）、`name`、`city`、`category`（`restaurant`/`hotel`）、`lat`、`lng`、`address`、`tel`、`photo_url`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_amap_poi.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_amap_poi.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.api.amap_poi'`）

- [ ] **Step 3: 实现 amap_poi.py**

创建 `backend/app/api/amap_poi.py`：

```python
"""高德 POI 检索：行程餐厅/酒店候选（真实商家，替代 LLM 编造的示例数据）。

调 restapi.amap.com/v3/place/text（extensions=all 才有 photos 字段）。
AMAP_KEY 未配置 / 请求失败 / status!=1 → 返回 []（planner 降级为示例数据模式）。
http_get 可注入，测试全 mock 无网络。评分/人均价高德实测不返回，不处理。
"""
from __future__ import annotations

import os
import re
import urllib.parse

import requests
from fastapi import APIRouter

AMAP_URL = "https://restapi.amap.com/v3/place/text"
FOOD_TYPE = "050000"    # 餐饮服务
HOTEL_TYPE = "100000"   # 住宿服务
FOOD_MAIN = "餐饮服务"
HOTEL_MAIN = "住宿服务"
BRANCH_SUFFIX_RE = re.compile(r"[（(][^（()）]{0,10}店[）)]$")  # 分店后缀（观锦餐厅(天府新谷店)）


class AmapPoiService:
    """高德 POI 搜索 → 过滤主分类 → 分店去重 → 解析为候选条目。"""

    def __init__(self, http_get=None) -> None:
        self.http_get = http_get or requests.get

    def search_restaurants(self, city: str) -> list[dict]:
        return self._search(city, FOOD_TYPE, FOOD_MAIN, "restaurant")

    def search_hotels(self, city: str) -> list[dict]:
        return self._search(city, HOTEL_TYPE, HOTEL_MAIN, "hotel")

    def _search(self, city: str, poi_type: str, main_type: str, category: str) -> list[dict]:
        key = os.environ.get("AMAP_KEY")
        if not key:
            return []  # 无 key：planner 走示例数据模式
        q = urllib.parse.urlencode({
            "key": key, "city": city, "citylimit": "true",
            "offset": "20", "page": "1", "extensions": "all"})
        try:
            resp = self.http_get(f"{AMAP_URL}?{q}&types={poi_type}", timeout=8)
        except (requests.RequestException, TimeoutError, OSError):
            return []
        if getattr(resp, "status_code", 200) != 200:
            return []
        data = resp.json()
        if not isinstance(data, dict) or data.get("status") != "1":
            return []
        out: list[dict] = []
        seen: set[str] = set()
        for p in data.get("pois") or []:
            if not isinstance(p, dict) or not str(p.get("type") or "").startswith(main_type):
                continue  # 裸搜会混入其他分类（如美食结果里的住宿服务）
            name = str(p.get("name") or "").strip()
            base = BRANCH_SUFFIX_RE.sub("", name)
            if not name or base in seen:
                continue  # 同一连锁分店只留第一条
            seen.add(base)
            loc = str(p.get("location") or "")
            if "," not in loc:
                continue
            lng, lat = loc.split(",", 1)
            photos = p.get("photos") or []
            out.append({
                "poi_id": f"amap-{p.get('id')}",
                "name": name, "city": city, "category": category,
                "lat": float(lat), "lng": float(lng),
                "address": str(p.get("address") or "").strip() or None,
                "tel": str(p.get("tel") or "").strip() or None,
                "photo_url": photos[0].get("url") if photos else None,
            })
            if len(out) >= 10:
                break
        return out


router = APIRouter()


@router.get("/api/amap-poi")
def amap_poi(city: str, type: str = "restaurant") -> dict:
    """调试/演示：查目的地真实餐厅/酒店候选（type: restaurant|hotel）。"""
    if type == "hotel":
        return {"items": service.search_hotels(city)}
    return {"items": service.search_restaurants(city)}


service = AmapPoiService()
```

修改 `backend/app/main.py`：

```python
from app.api.amap_poi import router as amap_poi_router
```
（与 `from app.api.attraction_image import router as attraction_image_router` 同行区，加在它后面）和：

```python
app.include_router(attraction_image_router)
app.include_router(amap_poi_router)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_amap_poi.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: 跑全量确认无回归**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest -q`
Expected: PASS（159 passed）

- [ ] **Step 6: Commit**

```bash
cd /d/agent && git add backend/app/api/amap_poi.py backend/app/main.py backend/tests/test_amap_poi.py
git commit -m "feat: 高德 POI 检索模块（餐厅/酒店候选：过滤/去重/照片，无 key 降级为空）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: enrich_itinerary 附加真实商家字段

**Files:**
- Modify: `backend/app/itinerary.py:44`（field 列表）
- Modify: `backend/tests/test_itinerary.py`

**Interfaces:**
- Consumes: Task 1 的候选条目字段（`poi_id`/`address`/`tel`/`photo_url`）
- Produces: 行程条目可携带 `address`/`tel`/`photo_url`（有值时附加，None 不附加）

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_itinerary.py`：

```python
AMAP_CANDIDATES = [
    {"poi_id": "amap-B0FFH1", "name": "马旺子·川小馆(太古里店)", "city": "成都",
     "category": "restaurant", "lat": 30.6512, "lng": 104.0825,
     "address": "中纱帽街8号", "tel": "028-88888888", "photo_url": "https://a.amap.com/p1.jpg"},
    {"poi_id": "amap-B0FFH9", "name": "世外桃源酒店", "city": "成都",
     "category": "hotel", "lat": 30.66, "lng": 104.09,
     "address": None, "tel": None, "photo_url": None},
]


def test_enrich_attaches_amap_restaurant_fields():
    """引用 amap- poi_id 的餐厅条目附加真实商家字段（地址/电话/照片）。"""
    it = {"days": [{"day": 1, "title": "x", "weather_note": "",
                    "items": [{"name": "马旺子·川小馆(太古里店)", "poi_id": "amap-B0FFH1",
                               "note": "午餐", "detail": "招牌：川菜"}]}],
          "summary": "", "warnings": []}
    item = enrich_itinerary(it, AMAP_CANDIDATES)["days"][0]["items"][0]
    assert item["category"] == "restaurant"
    assert item["address"] == "中纱帽街8号"
    assert item["tel"] == "028-88888888"
    assert item["photo_url"] == "https://a.amap.com/p1.jpg"
    assert item["lat"] == 30.6512 and item["lng"] == 104.0825


def test_enrich_omits_none_amap_fields():
    """候选缺地址/电话/照片（None）时条目不附加这些字段。"""
    it = {"days": [{"day": 1, "title": "x", "weather_note": "",
                    "items": [{"name": "世外桃源酒店", "poi_id": "amap-B0FFH9",
                               "note": ""}]}],
          "summary": "", "warnings": []}
    item = enrich_itinerary(it, AMAP_CANDIDATES)["days"][0]["items"][0]
    assert item["category"] == "hotel"
    assert "address" not in item and "tel" not in item and "photo_url" not in item
    assert item["lat"] == 30.66 and item["lng"] == 104.09
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_itinerary.py -q`
Expected: FAIL（`assert item["address"] == "中纱帽街8号"` → KeyError: 'address'）

- [ ] **Step 3: 扩展 field 列表**

修改 `backend/app/itinerary.py:44`：

```python
            for field in ("lat", "lng", "name", "category", "reason", "description", "poi_id", "city",
                          "address", "tel", "photo_url"):
```

（现有 `if cand.get(field) is not None` 保证 None 字段不附加；注释上方加一行说明：真实商家字段来自高德候选。）

- [ ] **Step 4: 跑测试确认通过 + 全量**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_itinerary.py -q && .venv/Scripts/python -m pytest -q`
Expected: PASS（161 passed）

- [ ] **Step 5: Commit**

```bash
cd /d/agent && git add backend/app/itinerary.py backend/tests/test_itinerary.py
git commit -m "feat: enrich 附加高德真实商家字段（address/tel/photo_url，None 不附加）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: planner 集成（高德候选 + 提示词 + 上下文）

**Files:**
- Modify: `backend/app/agents/planner.py`
- Modify: `backend/tests/test_planner.py`（加 autouse fixture 隔离高德 + 新用例）

**Interfaces:**
- Consumes: Task 1 `amap_poi.service`（模块级单例）
- Produces: `planner._amap_service`（模块级注入点，测试 monkeypatch 替换）；候选上下文含"候选餐厅/酒店"段；LLM 引用 `amap-{id}` 后 enrich 附字段

- [ ] **Step 1: 写失败测试**

修改 `backend/tests/test_planner.py`：

顶部加 import（第 5 行后）：

```python
import pytest
```

加 fixture + FakeAmap（放在 `_fake()` 之前）：

```python
class FakeAmap:
    """测试替身高德检索：默认空（既有测试降级为示例数据模式，调用次数可查）。"""

    def __init__(self, restaurants=None, hotels=None) -> None:
        self.restaurants = restaurants or []
        self.hotels = hotels or []
        self.calls: list[str] = []

    def search_restaurants(self, city: str) -> list:
        self.calls.append(city)
        return self.restaurants

    def search_hotels(self, city: str) -> list:
        self.calls.append(city)
        return self.hotels


@pytest.fixture(autouse=True)
def _no_amap(monkeypatch):
    """所有 planner 测试默认无高德候选（隔离网络，走示例数据降级路径）。"""
    monkeypatch.setattr(planner, "_amap_service", FakeAmap())
```

加新用例（文件末尾）：

```python
AMAP_RESTAURANT = {"poi_id": "amap-B0FFH1", "name": "马旺子·川小馆(太古里店)",
                   "city": "广州", "category": "restaurant", "lat": 23.12, "lng": 113.32,
                   "address": "中纱帽街8号", "tel": "028-88888888",
                   "photo_url": "https://a.amap.com/p1.jpg"}
AMAP_HOTEL = {"poi_id": "amap-B0FFH9", "name": "世外桃源酒店", "city": "广州",
              "category": "hotel", "lat": 23.13, "lng": 113.31,
              "address": "天河路1号", "tel": "020-12345678", "photo_url": None}


def test_planner_queries_amap_and_injects_candidates(monkeypatch):
    """planner 按候选城市查高德美食/酒店；真实商家进候选上下文。"""
    amap = FakeAmap(restaurants=[AMAP_RESTAURANT], hotels=[AMAP_HOTEL])
    monkeypatch.setattr(planner, "_amap_service", amap)
    fake = _fake()
    planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert amap.calls == ["广州", "广州"]  # 美食 + 酒店各一次
    prompt = fake.calls[0][-1]["content"]
    assert "候选餐厅" in prompt and "马旺子·川小馆" in prompt
    assert "候选酒店" in prompt and "世外桃源酒店" in prompt
    assert "中纱帽街8号" in prompt  # 地址进上下文（LLM 可引用）


def test_planner_enriches_amap_referenced_items(monkeypatch):
    """行程引用 amap- poi_id 的餐厅条目被 enrich 附真实字段（地址/电话/照片）。"""
    amap = FakeAmap(restaurants=[AMAP_RESTAURANT], hotels=[AMAP_HOTEL])
    monkeypatch.setattr(planner, "_amap_service", amap)
    itin = {"days": [{"day": 1, "title": "广州美食", "weather_note": "晴",
                      "items": [{"name": "广州塔", "poi_id": "guangzhou-001",
                                 "suggested_time": "建议晚上 19:00 后前往",
                                 "time_reason": "夜景绝佳", "note": "夜景",
                                 "detail": "广州塔高600米，昵称小蛮腰。"},
                                {"name": "马旺子·川小馆(太古里店)", "poi_id": "amap-B0FFH1",
                                 "note": "午餐", "detail": "招牌：川菜"}]}],
            "accommodation": [], "summary": "OK", "warnings": []}
    fake = FakeProvider(json_responses={"行程": itin})
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    food = out["itinerary"]["days"][0]["items"][1]
    assert food["category"] == "restaurant"
    assert food["address"] == "中纱帽街8号"
    assert food["tel"] == "028-88888888"
    assert food["photo_url"] == "https://a.amap.com/p1.jpg"
    assert food["lat"] == 23.12 and food["lng"] == 113.32


def test_planner_amap_failure_falls_back_to_examples(monkeypatch):
    """高德候选为空（无 key/失败）→ 上下文无餐厅段，LLM 照旧编示例，行为不变。"""
    monkeypatch.setattr(planner, "_amap_service", FakeAmap())
    fake = _fake()
    planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    prompt = fake.calls[0][-1]["content"]
    assert "候选餐厅" not in prompt and "候选酒店" not in prompt
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_planner.py -q`
Expected: FAIL（`AttributeError: module 'app.agents.planner' has no attribute '_amap_service'`）

- [ ] **Step 3: 实现 planner 集成**

修改 `backend/app/agents/planner.py`：

a) 顶部 import（第 14 行 `from app.llm.deepseek import DeepSeekProvider` 后）：

```python
from app.api import amap_poi as amap_poi_mod
```

b) 模块级注入点（放 `PLANNER_SYSTEM_PROMPT` 定义之前）：

```python
# 高德真实餐厅/酒店检索（模块级注入点：测试 monkeypatch 替换为 FakeAmap）
_amap_service = amap_poi_mod.service
```

c) `build_candidate_context` 重写（景点行 + 餐厅/酒店段）：

```python
def build_candidate_context(candidates: list[dict]) -> str:
    """把候选（景点 + 高德真实餐厅/酒店）拼成 LLM 上下文。"""
    lines = ["候选景点（必须从中选景点并引用 poi_id）:"]
    for p in candidates:
        if p.get("category") in ("restaurant", "hotel"):
            continue
        reason = f"，推荐理由：{p['reason']}" if p.get("reason") else ""
        lines.append(f"- {p['name']}（{p['city']}，评分{p['rating']}，价位档{p['price_tier']}）: {p['description']}{reason}")
    for label, category in (("候选餐厅（真实商家，从中引用 poi_id）:", "restaurant"),
                            ("候选酒店（真实商家，从中引用 poi_id）:", "hotel")):
        group = [p for p in candidates if p.get("category") == category]
        if not group:
            continue
        lines.append(label)
        for p in group:
            bits = [p["name"]]
            if p.get("address"):
                bits.append(f"地址：{p['address']}")
            if p.get("tel"):
                bits.append(f"电话：{p['tel']}")
            lines.append(f"- {'，'.join(bits)}")
    return "\n".join(lines) if lines else "（无候选景点）"
```

d) PLANNER_SYSTEM_PROMPT 更新——餐厅/酒店 schema 与规则（替换原有餐厅/酒店相关两处）：

原：
```
        {"name": "餐厅名（示例）", "note": "午餐（示例数据，由你基于常识生成）", "detail": "推荐美食，如 招牌：夫妻肺片、担担面，10-30 字"}
```
改为：
```
        {"name": "餐厅名", "poi_id": "候选餐厅的 poi_id（有候选餐厅时必须引用）", "note": "午餐/晚餐", "detail": "推荐美食，如 招牌：夫妻肺片、担担面，10-30 字"}
```

原（schema 末尾 accommodation 行）：
```
  "accommodation": [{"name": "酒店名（示例）", "days": [1, 2], ...}]
```
改为：
```
  "accommodation": [{"name": "候选酒店名", "poi_id": "候选酒店的 poi_id（有候选酒店时必须引用）", "days": [1, 2], "location_note": "酒店所在区域/附近景点，如 锦江区，近春熙路", "commute_note": "到景点通勤，如 到当日景点约 15-30 分钟车程", "price_note": "价格档位与预算符合性，如 中档，符合预算", "detail": "酒店环境与设施介绍，如 大堂现代、带健身房与自助早餐，近地铁口，10-30 字"}]
```

规则区（第 41 行 `- 酒店与餐厅是示例数据：由你基于目的地常识生成名称，名称后标注（示例），不要填 poi_id`）改为：
```
- 餐厅/酒店条目必须从候选餐厅/酒店中选取并引用其 poi_id（真实商家）；仅当候选餐厅/酒店不足时才可编造并在名称后标注（示例）且不填 poi_id
```

e) `planner_node` 集成（在 `candidates: list[dict] = state.get("candidates", [])` 与降级检查之间，即第 203-204 行处）：

原：
```python
    candidates: list[dict] = state.get("candidates", [])
    if region_resolved is True and not candidates:
```
改为：
```python
    candidates: list[dict] = state.get("candidates", [])
    if region_resolved is True and candidates:
        # 高德真实餐厅/酒店候选（无 key/失败返回 [] → LLM 照旧编示例数据）
        city = candidates[0].get("city")
        if city:
            candidates = (candidates
                          + _amap_service.search_restaurants(city)
                          + _amap_service.search_hotels(city))
    if region_resolved is True and not candidates:
```

（`candidate_ids` 与 `enrich_itinerary(itinerary, candidates)` 已用扩展后的 candidates——`_clean_itinerary` 会放行 `amap-` 前缀 id，enrich 按 poi_id 附加字段，无需其他改动。）

- [ ] **Step 4: 跑测试确认通过 + 全量**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest tests/test_planner.py -q && .venv/Scripts/python -m pytest -q`
Expected: PASS（164 passed）

- [ ] **Step 5: Commit**

```bash
cd /d/agent && git add backend/app/agents/planner.py backend/tests/test_planner.py
git commit -m "feat: planner 接入高德餐厅/酒店候选（引用 poi_id，无 key 降级示例数据）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 前端展示（地址/电话/照片 + 地图三类配色）

**Files:**
- Modify: `frontend/src/components/TripView.tsx`
- Modify: `frontend/src/components/AttractionImage.tsx`
- Modify: `frontend/src/components/ItineraryMap.tsx`

**Interfaces:**
- Consumes: 后端行程条目新字段 `address`/`tel`/`photo_url`、`category`（restaurant/hotel/attraction）
- Produces: 条目显示地址/电话行；餐厅/酒店照片用高德直链；地图 marker 按类别配色、popup 显示地址；行程底部高德数据说明

- [ ] **Step 1: 修改 AttractionImage（photoUrl 直链优先）**

`frontend/src/components/AttractionImage.tsx` 全量重写：

```tsx
/** 景点/商家图片：优先高德真实照片直链（photoUrl，餐厅/酒店 100% 覆盖）；
 * 无则从后端 /api/attraction-image 取必应搜索（景点）。
 * city 用于消除搜索歧义（如"南桥"会命中主板芯片，需搜"都江堰 南桥"）。 */
export default function AttractionImage({
  name,
  city,
  photoUrl,
}: {
  name: string;
  city?: string;
  photoUrl?: string;
}) {
  const [searchedUrl, setSearchedUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const url = photoUrl || searchedUrl;

  useEffect(() => {
    if (photoUrl) return; // 高德照片直链优先，无需搜索
    let alive = true;
    const params = new URLSearchParams({ name });
    if (city) params.set("city", city);
    fetch(`/api/attraction-image?${params.toString()}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { url?: string | null } | null) => {
        if (!alive) return;
        setSearchedUrl(d?.url ?? null);
        setFailed(!d?.url);
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [name, city, photoUrl]);

  return (
    <div className="relative mt-2 overflow-hidden rounded-lg">
      {url ? (
        <img
          src={url}
          alt={name}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
          className="h-36 w-full object-cover"
        />
      ) : (
        !failed && (
          <div className="flex h-36 w-full items-center justify-center bg-slate-100 text-xs text-slate-400">
            图片加载中…
          </div>
        )
      )}
      {failed && (
        <div className="flex h-36 w-full items-center justify-center bg-slate-100 text-xs text-slate-400">
          图片加载失败
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 修改 TripView（字段 + 地址电话行 + 传 photoUrl + 高德说明）**

`frontend/src/components/TripView.tsx`：

a) import 增加图标（第 5-9 行处）：

```tsx
import {
  BulbOutlined,
  ClockCircleOutlined,
  CloudOutlined,
  EnvironmentOutlined,
  HomeOutlined,
  PhoneOutlined,
} from "@ant-design/icons";
```

b) TripItem 接口加字段（第 24-25 行 `category?: string;` 后）：

```tsx
  category?: string;
  city?: string;
  // 高德真实商家（餐厅/酒店）：地址/电话/照片
  address?: string;
  tel?: string;
  photo_url?: string;
}
```

c) 条目渲染：地址/电话行（在 `{it.detail && ...}` 块之前插入），并传 photoUrl（第 171-173 行）：

```tsx
                  {(it.address || it.tel) && (
                    <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-slate-500">
                      {it.address && (
                        <span>
                          <EnvironmentOutlined className="mr-0.5 text-brand" />
                          {it.address}
                        </span>
                      )}
                      {it.tel && (
                        <span>
                          <PhoneOutlined className="mr-0.5 text-brand" />
                          {it.tel}
                        </span>
                      )}
                    </div>
                  )}
                  {(it.poi_id || it.category === "attraction") && (
                    <AttractionImage name={it.name} city={it.city} photoUrl={it.photo_url} />
                  )}
```

d) 底部高德说明（第 246 行 `</div>` 前，总结卡之后）：

```tsx
      <p className="text-center text-xs text-slate-400">
        餐厅/酒店数据来自高德地图，营业信息可能变动
      </p>
```

- [ ] **Step 3: 修改 ItineraryMap（三类配色 + popup 地址）**

`frontend/src/components/ItineraryMap.tsx`：

a) `MapPoint` 加字段（第 6-13 行）：

```tsx
export interface MapPoint {
  name: string;
  lat: number;
  lng: number;
  suggested_time?: string;
  time_reason?: string;
  note?: string;
  category?: string;
  address?: string;
}
```

b) 类别配色 + makeIcon 加参数（第 25-33 行）：

```tsx
// 三类标记配色：景点=品牌色，餐厅=橙，酒店=蓝（真实商家接入后地图区分）
const CATEGORY_COLORS: Record<string, string> = {
  attraction: BRAND,
  restaurant: "#f59e0b",
  hotel: "#3b82f6",
};

// 自定义 divIcon：bundler 下 Leaflet 默认 marker 图标资源会 404，圆形编号标记规避
function makeIcon(day: number, index: number, category?: string) {
  const bg = (category && CATEGORY_COLORS[category]) || BRAND;
  return L.divIcon({
    className: "",
    html: `<div style="background:${bg};color:#fff;border-radius:9999px;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:11px;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)">${day}-${index + 1}</div>`,
    iconSize: [20, 20],
    iconAnchor: [10, 10],
  });
}
```

c) Marker 调用与 Popup（第 69-81 行）：

```tsx
            <Marker
              key={`${d.day}-${i}`}
              position={[p.lat, p.lng]}
              icon={makeIcon(d.day, i, p.category)}
            >
              <Popup>
                <div className="text-xs">
                  <p className="font-semibold">{p.name}</p>
                  {p.address && <p>{p.address}</p>}
                  {p.suggested_time && (
                    <p>
                      建议{p.suggested_time}
                      {p.time_reason ? `（${p.time_reason}）` : ""}
                    </p>
                  )}
                  {p.note && <p>{p.note}</p>}
                </div>
              </Popup>
            </Marker>
```

- [ ] **Step 4: 修改 TripView geoDays（MapPoint 带 category/address）**

`frontend/src/components/TripView.tsx` 第 88-101 行 `.map((it) => ({` 内加：

```tsx
          .map((it) => ({
            name: it.name,
            lat: it.lat,
            lng: it.lng,
            suggested_time: it.suggested_time,
            time_reason: it.time_reason,
            note: it.note,
            category: it.category,
            address: it.address,
          })),
```

- [ ] **Step 5: 门禁验证**

Run: `cd /d/agent/frontend && npm run build && npm run lint`
Expected: `✓ built` 0 错误；lint 仅既有 `TripView.tsx:104` exhaustive-deps warning（不新增）

- [ ] **Step 6: Commit**

```bash
cd /d/agent && git add frontend/src/components/AttractionImage.tsx frontend/src/components/TripView.tsx frontend/src/components/ItineraryMap.tsx
git commit -m "feat: 前端展示高德真实商家（地址/电话/照片直链 + 地图三类配色）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 冒烟验证 + README + 收尾

**Files:**
- Modify: `README.md`（功能说明）
- 无代码测试（手动冒烟用真实高德 key）

- [ ] **Step 1: 后端重启 + 冒烟（真实高德 key）**

Run:
```bash
# 重启后端（改代码必须重启）
taskkill //F //PID $(netstat -ano | grep ':8000' | grep LISTENING | awk '{print $5}' | head -1)
cd /d/agent/backend && .venv/Scripts/uvicorn app.main:app --port 8000
```
（后台启动后）验证真实候选：
```bash
curl -s "http://localhost:8000/api/amap-poi?city=%E6%88%90%E9%83%BD&type=restaurant"
```
Expected: `{"items":[...]}`，含真实成都餐厅（name/address/tel/photo_url，poi_id 以 `amap-` 开头），10 条以内

- [ ] **Step 2: 端到端冒烟（成都行程）**

Run: 浏览器 `http://localhost:5173` → 发送 `10月去成都玩3天，预算8000，喜欢美食`
Expected: 行程餐厅条目显示真实店名 + 地址 + 电话 + 高德照片；酒店条目同理；地图出现橙/蓝点；无"（示例）"条目（候选充足时）；失败降级时仍显示（示例）

- [ ] **Step 3: README 更新**

`README.md` 功能清单补充（找到餐厅/酒店相关描述处，如"行程含餐厅/酒店（示例数据）"）：

```markdown
- 餐厅/酒店为高德地图真实商家（地址/电话/照片，地图打点）；无高德 key 时自动降级为示例数据
```

（并在环境变量说明处补一行 `AMAP_KEY`：高德开放平台 Web 服务 key，可选，缺失时餐厅/酒店为示例数据）

- [ ] **Step 4: 全量回归**

Run: `cd /d/agent/backend && .venv/Scripts/python -m pytest -q && cd /d/agent/frontend && npm run build`
Expected: PASS（164 passed）+ `✓ built`

- [ ] **Step 5: Commit**

```bash
cd /d/agent && git add README.md
git commit -m "docs: README 补充高德真实餐厅/酒店（AMAP_KEY 环境变量）

Co-Authored-By: Claude <noreply@anthropic.com>"
```
