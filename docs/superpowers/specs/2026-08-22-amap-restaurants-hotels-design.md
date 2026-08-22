# 真实餐厅/酒店接入设计（高德 POI）

**Goal:** 行程中的餐厅/酒店从"LLM 编造的示例数据"升级为高德地图真实商家（地址/电话/坐标/照片），解决"（示例）"标记与"图片怎么是这样的"的根因问题。

**Architecture:** 新增高德 POI 检索模块，行程规划时按目的地城市查美食/酒店候选，随景点候选一起进 LLM 上下文（引用 poi_id 机制不变），enrich 附真实字段；无 key/失败时降级为现有"（示例）"模式。

## 实测结论（2026-08-22，成都）

| 字段 | v3 place/text (extensions=all) | v5 place/text |
|---|---|---|
| 地址 | 19/20 ✅ | ✅ |
| 电话 | 19/20 ✅ | 部分 |
| 坐标 | 20/20 ✅ | ✅ |
| 照片 photos[].url | 20/20（每家 3 张）✅ | ❌ 不返回 |
| 评分 rating | ❌ 全部缺失 | ❌ 全部缺失 |
| 人均价 price | ❌ 全部缺失 | ❌ 全部缺失 |

- **v3 带照片、v5 不带** → 用 v3（extensions=all）
- **评分/人均价不可用** → 前端不显示评分；预算价位匹配不做（原草案第 3 点取消）
- 裸搜 types=050000 会混入"住宿服务"等（云隐小院）；关键词搜索（如"川菜"）会重复同一连锁分店（观锦餐厅×3 店）→ 需过滤 + 去重
- 照片 100% 覆盖 → 餐厅/酒店图片直接用高德照片（比必应搜索可靠得多，内容 100% 相关）

## 数据流

```
planner_node
  → amap_poi.search_restaurants(city) + search_hotels(city)   # 各 ~10 条，失败返回 []
  → 候选上下文 = 景点 candidates + 餐厅/酒店候选（带 poi_id="amap-{id}"）
  → LLM 引用 poi_id（机制与景点一致）
  → enrich_itinerary 匹配多来源候选（景点 + 餐厅 + 酒店）附字段
  → 前端展示地址/电话/照片 + 地图打点
```

## 模块设计

### 新文件 `backend/app/api/amap_poi.py`

- `AMAP_KEY = os.environ.get("AMAP_KEY")`；key 缺失 → `enabled = False`（降级开关）
- `search_pois(city, poi_type, keywords="") -> list[dict]`：调 `restapi.amap.com/v3/place/text`，参数 `key/city/citylimit=true/extensions=all/offset=20/page=1`，`types=050000`(美食) 或 `100000`(酒店)
- 过滤：`type` 主分类必须 `餐饮服务`（美食）/ `住宿服务`（酒店），剔除混入项
- 去重：name 去掉 `(xxx店)`/`（xxx店）` 分店后缀后相同者只留第一条
- 返回条目：`{"poi_id": f"amap-{id}", "name", "city", "category": "restaurant"|"hotel", "lat", "lng", "address", "tel", "photo_url"}`（photo 取 photos[0].url）
- `http_get` 可注入（测试全 mock）；异常/配额超限/无 key → 返回 `[]`
- 模块级 `service = AmapPoiService()`；路由 `GET /api/amap-poi?city=&type=`（可选，调试/演示用）

### 改 `backend/app/agents/planner.py`

- `planner_node`：`restaurants, hotels = amap_poi.search_*(city)`（city 从 profile.destination 解析的城市取——现状 candidate 城市字段；简化：取 candidates[0].city）
- `build_candidate_context` 扩展：景点候选后追加"候选餐厅/酒店"段（含 poi_id/地址/电话，detail 空）
- PLANNER_SYSTEM_PROMPT 更新：餐厅/酒店条目**必须**从候选餐厅/酒店中引用 poi_id（不再编"（示例）"）；候选不足时可编（示例）兜底
- 规则调整：`_clean_itinerary` 的 candidate_ids 集合包含全部三类候选 id（amap- 前缀天然区分）
- `enrich_itinerary` 的 candidates 参数改为合并列表（景点 + 餐厅 + 酒店）

### 改 `backend/app/itinerary.py`（enrich）

- field 列表扩展：`address`, `tel`, `photo_url`（仅对应候选有值时附加）
- detail 兜底逻辑不变（餐厅/酒店候选无 description → 不附加）

### 改前端

- `TripView.tsx`：`TripItem` 加 `address?/tel?/photo_url?`；餐厅/酒店条目渲染地址（📌 前缀）、电话（☎ 前缀）小字行
- `AttractionImage.tsx`：加可选 `photoUrl` prop——有值直接用（高德照片直链，`referrerPolicy` 已 no-referrer），无值走必应搜索
- 地图：geoDays 已按"有 lat/lng"上图 → 餐厅/酒店自动打点；`ItineraryMap` marker 按 `category` 换色（attraction=品牌色、restaurant=橙色、hotel=蓝色），popup 显示地址
- 免责声明：地图免责声明逐字保留；在行程底部加一行"餐厅/酒店数据来自高德地图，营业信息可能变动"

### 降级路径

- `AMAP_KEY` 未配置 / 高德超时 / 配额耗尽 / 返回空 → 餐厅/酒店候选为空 → LLM 照旧编"（示例）"条目 → 现有行为不变（前端图片照旧必应）

## 测试

- `tests/test_amap_poi.py`（新）：FakeHttp 注入；断言解析/过滤/去重/photo 提取；无 key、503、空结果返回 []
- `tests/test_planner.py`：候选含 amap- poi_id 的行程 → enrich 附 address/tel/photo_url；餐厅条目引用 amap id 后不再标（示例）
- `tests/test_itinerary.py`：合并候选匹配 amap- poi_id；address/tel/photo_url 附加；候选无这些字段时不附加
- 全量 pytest + 前端 build/lint

## 不做（YAGNI）

- 评分/人均价展示（高德不返回该字段）
- 预算-价位匹配（依赖 price 字段，实测缺失）
- 餐厅/酒店搜索词优化（多菜系并行查询）
- 前端分店去重展示（后端已去重）
- **景点数据接高德/景点坐标校准**（用户确认：景点保持 RAG 语料体系，语料含评分/票价/详细介绍，高德 place/text 不返回这些字段；高德仅服务餐厅/酒店与地图）
