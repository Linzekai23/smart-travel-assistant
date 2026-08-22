# M3 完整协作 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 M2 的双节点图升级为 5 Agent 完整协作图（analyst → ‖researcher‖budget‖ → planner → supervisor），并把 RAG 知识库重构为全国 34 省级行政区著名景点库（三级粒度检索）。

**Architecture:** LangGraph StateGraph 节点级并行 fan-out（researcher 与 budget 两分支并行，join 后进 planner，终节点 supervisor）。RAG 重构为确定性数据层：province_cities 映射表 + 省份模板语料生成 + Chroma（metadata 含 province/city）+ 三级 fallback 检索。所有 LLM 产出保持结构化 JSON，展示文本由确定性格式化函数生成（spec 风险对策"结构化状态，减少自由文本流转"）。

**Tech Stack:** Python 3.11+ · LangGraph 1.2.x（StateGraph + CompiledStateGraph）· FastAPI · Chroma + BGE（bge-small-zh-v1.5）· React 19 + TS

**Spec:** [docs/superpowers/specs/2026-08-19-travel-assistant-design.md](../../superpowers/specs/2026-08-19-travel-assistant-design.md)（2026-08-20 M3 修订版，commit d75bfd0）

## Global Constraints

1. **私有 key 最高机密**：DEEPSEEK_API_KEY 绝不写入任何文件、绝不打印、绝不进入 commit。只通过进程环境变量使用。
2. 所有 commit message 必须以 `Co-Authored-By: Claude <noreply@anthropic.com>` 结尾。
3. **测试全 mock**（FakeProvider / FakeEmbedder / fake_weather / fake 检索注入），无网络、无模型下载；真实 LLM/BGE 仅 Task 8 手动冒烟。
4. 行程城市限国内。34 省级行政区 = 23 省 + 5 自治区 + 4 直辖市 + 2 特别行政区（含港澳台）。
5. 语料**只存景点**（category 恒为 `"attraction"`）；酒店/餐厅由 Planner 的 LLM 生成（名称标注"（示例）"，无 poi_id）。
6. 语料标注"AI 生成示例数据，坐标仅供参考"（generate 提示词与 README 均注明）。
7. **删除替换**：执行时删除旧 20 城语料（`backend/data/poi_corpus.jsonl`）与 Chroma 向量库（`backend/data/chroma`），重建不保留（spec §4）。
8. 三级粒度检索：搜省→全省景点；搜库内城市→该市景点；搜库外城市→所在省景点（province_cities 映射表，确定性）。
9. 坐标校验：ingest 校验景点坐标在**城市中心 ±2°** 内，越界丢弃（spec §8）。
10. 每省 2-4 个景点城市（poi_cities）、4-6 个景点条目；`poi_id = {城市拼音}-{序号:03d}`。
11. LLM 只产出结构化 JSON；回复文本一律由确定性格式化函数拼装。
12. 前端 Agent 面板 `AGENT_NAMES` 扩展 5 个 agent；预算表以 markdown 嵌入回复展示（不新建组件，结构化 BudgetTable 组件留 M5）。

---

### Task 1: province_cities 数据模块

**Files:**
- Create: `backend/app/rag/province_cities.py`
- Test: `backend/tests/test_province_cities.py`

**Interfaces:**
- Consumes: 无（独立数据模块）
- Produces（后续任务依赖的精确签名）:
  - `PROVINCES: dict[str, dict]` —— key=省份简称（"广东"）；value=`{"alias": list[str], "cities": list[str], "poi_cities": dict[str, tuple[str, tuple[float, float]]]}`；`poi_cities` 为 {城市名: (拼音, (lat, lng))}，**键的顺序 = 生成语料的城市顺序，第一项即省会/首府**
  - `PROVINCE_ALIASES: dict[str, str]` —— 别名（全称如"广东省"、简称"粤"、拼音"guangdong"）→ 省份简称，全小写键
  - `CITY_TO_PROVINCE: dict[str, str]` —— 城市名 → 省份简称（由 PROVINCES 的 cities 生成）
  - `city_coord(province: str, city: str | None) -> tuple[float, float]` —— city 有值返回该城坐标；None 返回该省第一个 poi_city（省会）坐标；未知抛出 `KeyError`

- [ ] **Step 1: Write the failing test**

```python
"""test_province_cities.py"""
import pytest

from app.rag import province_cities as pc

# 34 省级行政区（标准口径：23 省 + 5 自治区 + 4 直辖市 + 2 特别行政区）
ALL_34 = {
    "北京", "上海", "天津", "重庆",
    "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建",
    "江西", "山东", "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州",
    "云南", "陕西", "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆",
    "香港", "澳门",
}


def test_provinces_cover_34():
    assert set(pc.PROVINCES) == ALL_34


def test_province_shape():
    for prov, d in pc.PROVINCES.items():
        assert d["alias"] and d["cities"] and d["poi_cities"]
        assert 2 <= len(d["poi_cities"]) <= 4, f"{prov}: 景点城市应为 2-4 个"
        assert set(d["poi_cities"]) <= set(d["cities"]), f"{prov}: poi_cities ⊆ cities"
        for city, (pinyin, (lat, lng)) in d["poi_cities"].items():
            assert pinyin.isascii(), f"{city}: 拼音必须是 ascii"
            assert 15 <= lat <= 55 and 70 <= lng <= 140, f"{city}: 坐标越界"


def test_aliases_resolve():
    assert pc.PROVINCE_ALIASES["广东省"] == "广东"
    assert pc.PROVINCE_ALIASES["粤"] == "广东"
    assert pc.PROVINCE_ALIASES["guangdong"] == "广东"
    assert pc.PROVINCE_ALIASES["北京市"] == "北京"
    assert pc.PROVINCE_ALIASES["xinjiang"] == "新疆"


def test_city_to_province():
    assert pc.CITY_TO_PROVINCE["广州"] == "广东"
    assert pc.CITY_TO_PROVINCE["佛山"] == "广东"   # 库外城市也必须有省归属（三级检索 fallback）
    assert pc.CITY_TO_PROVINCE["成都"] == "四川"


def test_city_coord():
    lat, lng = pc.city_coord("广东", "广州")
    assert abs(lat - 23.1291) < 0.01 and abs(lng - 113.2644) < 0.01
    lat, lng = pc.city_coord("广东", None)  # 省会坐标
    assert abs(lat - 23.1291) < 0.01
    with pytest.raises(KeyError):
        pc.city_coord("巴黎", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_province_cities.py -v`（在 backend/ 下）
Expected: FAIL with `ModuleNotFoundError: No module named 'app.rag.province_cities'`

- [ ] **Step 3: Write the implementation** — `backend/app/rag/province_cities.py`

数据表（**逐字使用，不得改动坐标与拼音**；`poi_cities` 键顺序 = 语料生成顺序，第一项为省会/首府）：

```python
"""全国 34 省级行政区城市-省份映射表（RAG 三级粒度检索的确定性依据）。

- PROVINCES: 省份简称 → {alias(全称/简称/拼音), cities(省内城市全清单), poi_cities(有景点的城市: {城市: (拼音, 中心坐标)})}
- PROVINCE_ALIASES / CITY_TO_PROVINCE: 由 PROVINCES 生成，normalize_region 据此解析
- 数据为演示用坐标（近似），真实展示以语料坐标为准
"""
from __future__ import annotations

PROVINCES: dict[str, dict] = {
    "北京": {"alias": ["北京市", "京", "beijing"], "cities": ["北京"],
             "poi_cities": {"北京": ("beijing", (39.9042, 116.4074))}},
    "上海": {"alias": ["上海市", "沪", "shanghai"], "cities": ["上海"],
             "poi_cities": {"上海": ("shanghai", (31.2304, 121.4737))}},
    "天津": {"alias": ["天津市", "津", "tianjin"], "cities": ["天津"],
             "poi_cities": {"天津": ("tianjin", (39.3434, 117.3616))}},
    "重庆": {"alias": ["重庆市", "渝", "chongqing"], "cities": ["重庆"],
             "poi_cities": {"重庆": ("chongqing", (29.5630, 106.5516))}},
    "河北": {"alias": ["河北省", "冀", "hebei"],
             "cities": ["石家庄", "唐山", "秦皇岛", "邯郸", "保定", "承德", "张家口"],
             "poi_cities": {"石家庄": ("shijiazhuang", (38.0428, 114.5149)),
                            "承德": ("chengde", (40.9515, 117.9636)),
                            "秦皇岛": ("qinhuangdao", (39.9354, 119.5997))}},
    "山西": {"alias": ["山西省", "晋", "shanxi"],
             "cities": ["太原", "大同", "晋中", "临汾", "运城", "忻州", "平遥"],
             "poi_cities": {"太原": ("taiyuan", (37.8706, 112.5489)),
                            "大同": ("datong", (40.0768, 113.3001)),
                            "平遥": ("pingyao", (37.1953, 112.1763))}},
    "内蒙古": {"alias": ["内蒙古自治区", "蒙", "neimenggu", "内蒙古"],
               "cities": ["呼和浩特", "包头", "鄂尔多斯", "呼伦贝尔", "赤峰", "通辽"],
               "poi_cities": {"呼和浩特": ("huhehaote", (40.8424, 111.7500)),
                              "呼伦贝尔": ("hulunbeier", (49.2122, 119.7658))}},
    "辽宁": {"alias": ["辽宁省", "辽", "liaoning"],
             "cities": ["沈阳", "大连", "鞍山", "抚顺", "本溪", "丹东", "锦州"],
             "poi_cities": {"沈阳": ("shenyang", (41.8057, 123.4315)),
                            "大连": ("dalian", (38.9140, 121.6147)),
                            "丹东": ("dandong", (40.1290, 124.3833))}},
    "吉林": {"alias": ["吉林省", "吉", "jilin"],
             "cities": ["长春", "吉林", "四平", "通化", "白山", "延吉"],
             "poi_cities": {"长春": ("changchun", (43.8171, 125.3235)),
                            "吉林": ("jilin", (43.8379, 126.5496))}},
    "黑龙江": {"alias": ["黑龙江省", "黑", "heilongjiang", "黑龙江"],
               "cities": ["哈尔滨", "齐齐哈尔", "牡丹江", "佳木斯", "大庆", "黑河"],
               "poi_cities": {"哈尔滨": ("haerbin", (45.8038, 126.5349)),
                              "牡丹江": ("mudanjiang", (44.5527, 129.6330))}},
    "江苏": {"alias": ["江苏省", "苏", "jiangsu"],
             "cities": ["南京", "苏州", "无锡", "常州", "南通", "扬州", "镇江", "徐州"],
             "poi_cities": {"南京": ("nanjing", (32.0603, 118.7969)),
                            "苏州": ("suzhou", (31.2989, 120.5853)),
                            "扬州": ("yangzhou", (32.3932, 119.4129))}},
    "浙江": {"alias": ["浙江省", "浙", "zhejiang"],
             "cities": ["杭州", "宁波", "温州", "嘉兴", "绍兴", "金华", "台州", "舟山"],
             "poi_cities": {"杭州": ("hangzhou", (30.2741, 120.1551)),
                            "宁波": ("ningbo", (29.8683, 121.5440)),
                            "绍兴": ("shaoxing", (30.0303, 120.5802))}},
    "安徽": {"alias": ["安徽省", "皖", "anhui"],
             "cities": ["合肥", "芜湖", "蚌埠", "淮南", "马鞍山", "安庆", "黄山", "亳州"],
             "poi_cities": {"合肥": ("hefei", (31.8206, 117.2272)),
                            "黄山": ("huangshan", (29.7147, 118.3376))}},
    "福建": {"alias": ["福建省", "闽", "fujian"],
             "cities": ["福州", "厦门", "泉州", "漳州", "莆田", "武夷山", "南平"],
             "poi_cities": {"福州": ("fuzhou", (26.0745, 119.2965)),
                            "厦门": ("xiamen", (24.4798, 118.0894)),
                            "泉州": ("quanzhou", (24.8741, 118.6757))}},
    "江西": {"alias": ["江西省", "赣", "jiangxi"],
             "cities": ["南昌", "九江", "上饶", "景德镇", "赣州", "吉安", "宜春"],
             "poi_cities": {"南昌": ("nanchang", (28.6820, 115.8579)),
                            "九江": ("jiujiang", (29.7051, 115.9928)),
                            "景德镇": ("jingdezhen", (29.2686, 117.1784))}},
    "山东": {"alias": ["山东省", "鲁", "shandong"],
             "cities": ["济南", "青岛", "烟台", "潍坊", "泰安", "威海", "淄博", "济宁"],
             "poi_cities": {"济南": ("jinan", (36.6512, 117.1201)),
                            "青岛": ("qingdao", (36.0671, 120.3826)),
                            "泰安": ("taian", (36.1857, 117.0876))}},
    "河南": {"alias": ["河南省", "豫", "henan"],
             "cities": ["郑州", "洛阳", "开封", "安阳", "南阳", "新乡", "焦作", "商丘"],
             "poi_cities": {"郑州": ("zhengzhou", (34.7466, 113.6254)),
                            "洛阳": ("luoyang", (34.6197, 112.4540)),
                            "开封": ("kaifeng", (34.7973, 114.3074))}},
    "湖北": {"alias": ["湖北省", "鄂", "hubei"],
             "cities": ["武汉", "宜昌", "襄阳", "荆州", "十堰", "黄冈", "恩施"],
             "poi_cities": {"武汉": ("wuhan", (30.5928, 114.3055)),
                            "宜昌": ("yichang", (30.6919, 111.2865)),
                            "十堰": ("shiyan", (32.6294, 110.7980))}},
    "湖南": {"alias": ["湖南省", "湘", "hunan"],
             "cities": ["长沙", "株洲", "湘潭", "衡阳", "岳阳", "常德", "张家界", "凤凰"],
             "poi_cities": {"长沙": ("changsha", (28.2282, 112.9388)),
                            "张家界": ("zhangjiajie", (29.1171, 110.4792)),
                            "凤凰": ("fenghuang", (27.9480, 109.5995))}},
    "广东": {"alias": ["广东省", "粤", "guangdong"],
             "cities": ["广州", "深圳", "珠海", "佛山", "东莞", "中山", "惠州", "汕头", "湛江", "韶关"],
             "poi_cities": {"广州": ("guangzhou", (23.1291, 113.2644)),
                            "深圳": ("shenzhen", (22.5431, 114.0579)),
                            "珠海": ("zhuhai", (22.2707, 113.5767)),
                            "韶关": ("shaoguan", (24.8104, 113.5975))}},
    "广西": {"alias": ["广西壮族自治区", "桂", "guangxi", "广西"],
             "cities": ["南宁", "桂林", "柳州", "北海", "梧州", "防城港", "钦州"],
             "poi_cities": {"南宁": ("nanning", (22.8170, 108.3665)),
                            "桂林": ("guilin", (25.2736, 110.2900)),
                            "北海": ("beihai", (21.4812, 109.1206))}},
    "海南": {"alias": ["海南省", "琼", "hainan"],
             "cities": ["海口", "三亚", "儋州", "琼海", "万宁"],
             "poi_cities": {"海口": ("haikou", (20.0442, 110.1999)),
                            "三亚": ("sanya", (18.2528, 109.5119))}},
    "四川": {"alias": ["四川省", "川", "蜀", "sichuan"],
             "cities": ["成都", "绵阳", "乐山", "宜宾", "泸州", "南充", "九寨沟", "西昌"],
             "poi_cities": {"成都": ("chengdu", (30.5728, 104.0668)),
                            "乐山": ("leshan", (29.5521, 103.7655)),
                            "九寨沟": ("jiuzhaigou", (33.2610, 103.9200))}},
    "贵州": {"alias": ["贵州省", "黔", "贵", "guizhou"],
             "cities": ["贵阳", "遵义", "安顺", "凯里", "铜仁", "六盘水"],
             "poi_cities": {"贵阳": ("guiyang", (26.6470, 106.6302)),
                            "遵义": ("zunyi", (27.7257, 106.9272)),
                            "安顺": ("anshun", (26.2455, 105.9476))}},
    "云南": {"alias": ["云南省", "滇", "云", "yunnan"],
             "cities": ["昆明", "大理", "丽江", "曲靖", "玉溪", "西双版纳", "香格里拉"],
             "poi_cities": {"昆明": ("kunming", (24.8801, 102.8329)),
                            "大理": ("dali", (25.6065, 100.2676)),
                            "丽江": ("lijiang", (26.8721, 100.2299)),
                            "西双版纳": ("xishuangbanna", (22.0089, 100.7940))}},
    "西藏": {"alias": ["西藏自治区", "藏", "xizang", "西藏"],
             "cities": ["拉萨", "日喀则", "林芝", "山南"],
             "poi_cities": {"拉萨": ("lasa", (29.6525, 91.1721)),
                            "林芝": ("linzhi", (29.6490, 94.3623))}},
    "陕西": {"alias": ["陕西省", "陕", "秦", "shaanxi"],
             "cities": ["西安", "咸阳", "宝鸡", "渭南", "延安", "汉中", "榆林"],
             "poi_cities": {"西安": ("xian", (34.3416, 108.9398)),
                            "延安": ("yanan", (36.5851, 109.4898))}},
    "甘肃": {"alias": ["甘肃省", "甘", "陇", "gansu"],
             "cities": ["兰州", "天水", "敦煌", "张掖", "嘉峪关", "酒泉", "武威"],
             "poi_cities": {"兰州": ("lanzhou", (36.0611, 103.8343)),
                            "敦煌": ("dunhuang", (40.1421, 94.6620)),
                            "张掖": ("zhangye", (38.9259, 100.4498))}},
    "青海": {"alias": ["青海省", "青", "qinghai"],
             "cities": ["西宁", "海东", "格尔木", "德令哈"],
             "poi_cities": {"西宁": ("xining", (36.6171, 101.7782))}},
    "宁夏": {"alias": ["宁夏回族自治区", "宁", "ningxia", "宁夏"],
             "cities": ["银川", "石嘴山", "吴忠", "中卫", "固原"],
             "poi_cities": {"银川": ("yinchuan", (38.4872, 106.2309)),
                            "中卫": ("zhongwei", (37.4999, 105.1968))}},
    "新疆": {"alias": ["新疆维吾尔自治区", "新", "xinjiang", "新疆"],
             "cities": ["乌鲁木齐", "喀什", "吐鲁番", "伊宁", "哈密", "克拉玛依"],
             "poi_cities": {"乌鲁木齐": ("wulumuqi", (43.8256, 87.6168)),
                            "喀什": ("kashi", (39.4704, 75.9898)),
                            "吐鲁番": ("tulufan", (42.9513, 89.1897))}},
    "台湾": {"alias": ["台湾省", "台", "taiwan", "台湾"],
             "cities": ["台北", "高雄", "台中", "台南", "花莲"],
             "poi_cities": {"台北": ("taibei", (25.0330, 121.5654)),
                            "高雄": ("gaoxiong", (22.6273, 120.3014))}},
    "香港": {"alias": ["香港特别行政区", "港", "xianggang", "香港"],
             "cities": ["香港"],
             "poi_cities": {"香港": ("xianggang", (22.3193, 114.1694))}},
    "澳门": {"alias": ["澳门特别行政区", "澳", "aomen", "澳门"],
             "cities": ["澳门"],
             "poi_cities": {"澳门": ("aomen", (22.1987, 113.5439))}},
}

# 别名（含"广东"自身等短名）→ 省份简称；键统一小写
PROVINCE_ALIASES: dict[str, str] = {}
for _prov, _d in PROVINCES.items():
    for _alias in (_prov, *_d["alias"]):
        PROVINCE_ALIASES[_alias.strip().lower()] = _prov

# 城市名 → 省份简称
CITY_TO_PROVINCE: dict[str, str] = {}
for _prov, _d in PROVINCES.items():
    for _city in _d["cities"]:
        CITY_TO_PROVINCE[_city] = _prov


def city_coord(province: str, city: str | None) -> tuple[float, float]:
    """城市中心坐标；city 为 None 时返回该省第一个 poi_city（省会/首府）。"""
    poi = PROVINCES[province]["poi_cities"]
    name = city or next(iter(poi))
    return poi[name][1]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_province_cities.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/province_cities.py backend/tests/test_province_cities.py
git commit -m "feat: 34-province city-province mapping table for 3-tier RAG retrieval

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 语料生成/入库重构（省份模板、景点-only、province metadata）

**Files:**
- Modify: `backend/app/rag/generate.py`（省份模板、`CITY_EN` 动态化、`validate_pois` 新规则）
- Modify: `backend/app/rag/ingest.py`（province 校验、poi_id 拼音、坐标二次校验）
- Modify: `backend/app/rag/vector_store.py`（metadata 加 province、`_where` 支持 province）
- Modify: `backend/tests/fixtures/sample_pois.jsonl`（改为景点-only + province）
- Test: `backend/tests/test_generate.py`、`backend/tests/test_ingest.py`、`backend/tests/test_vector_store.py`

**Interfaces:**
- Consumes: Task 1 的 `PROVINCES` / `city_coord`
- Produces（后续任务依赖）:
  - `generate.generate_province(provider, province) -> list[dict]`（条目含 province/city 字段）
  - `generate.PROVINCE_ORDER: list[str]`（34 省遍历顺序常量）
  - `generate.CITY_EN: dict[str, str]`（城市→拼音，**从 PROVINCES 动态生成，所有 poi_cities 城市**，保留导出供 retriever 使用）
  - `ingest.load_corpus(jsonl_path) -> list[dict]`（校验：province ∈ PROVINCES、city ∈ 该省 poi_cities、category == "attraction"、坐标在城市中心 ±2°；poi_id = `{pinyin}-{seq:03d}` 按城市计数）
  - `vector_store.VectorStore`：metadata 含 `province`；`query()`/`get_all()` 的 where 支持 `province`

- [ ] **Step 1: Write/update failing tests**

`backend/tests/test_generate.py` 更新（`generate_city` → `generate_province`；fixture 响应改为省份结构）：

```python
import pytest

from app.llm.deepseek import DeepSeekProvider
from app.rag import generate
from app.rag.province_cities import PROVINCES

from conftest import FakeProvider

PROVINCE_RESPONSE = {
    "province": "四川",
    "pois": [
        {"name": "宽窄巷子", "city": "成都", "lat": 30.67, "lng": 104.06,
         "rating": 4.6, "price_tier": 1, "description": "老成都街区，小吃与茶馆集中。",
         "tags": ["老街", "小吃"]},
        {"name": "峨眉山", "city": "乐山", "lat": 29.55, "lng": 103.77,
         "rating": 4.8, "price_tier": 2, "description": "佛教名山，金顶云海。",
         "tags": ["自然", "佛教"]},
        {"name": "非法城市景点", "city": "攀枝花", "lat": 26.58, "lng": 101.71,
         "rating": 4.0, "price_tier": 1, "description": "该城市不在本省 poi_cities。",
         "tags": []},
        {"name": "非法类别", "city": "成都", "category": "restaurant", "lat": 30.6,
         "lng": 104.0, "rating": 4.0, "price_tier": 3, "description": "餐厅不应出现在语料。",
         "tags": ["火锅"]},
    ],
}


def _fake() -> FakeProvider:
    return FakeProvider(json_responses={"四川": PROVINCE_RESPONSE})


def test_province_order_covers_34():
    assert len(generate.PROVINCE_ORDER) == 34
    assert generate.PROVINCE_ORDER[0] == "北京"
    assert set(generate.PROVINCE_ORDER) == set(PROVINCES)


def test_city_en_derived_from_provinces():
    assert generate.CITY_EN["广州"] == "guangzhou"
    assert generate.CITY_EN["成都"] == "chengdu"
    assert set(generate.CITY_EN) == {
        c for d in PROVINCES.values() for c in d["poi_cities"]
    }


def test_generate_province_parses():
    fake = _fake()
    pois = generate.generate_province(fake, "四川")  # type: ignore[arg-type]
    assert len(pois) == 2  # 非法城市与非法类别被丢弃
    assert pois[0]["name"] == "宽窄巷子"
    assert pois[0]["province"] == "四川" and pois[0]["city"] == "成都"
    assert fake.calls[0][0]["role"] == "system"
    assert "示例数据" in fake.calls[0][0]["content"]  # 语料标注


def test_validate_pois_checks_city_and_coord():
    good = {"name": "故宫", "city": "北京", "lat": 39.9, "lng": 116.4,
            "rating": 4.8, "price_tier": 2, "description": "紫禁城。", "tags": ["历史"]}
    bad_city = dict(good, name="外地景点", city="成都")
    bad_coord = dict(good, name="坐标越界", lat=80.0, lng=200.0)
    out = generate.validate_pois("北京", [good, bad_city, bad_coord])
    assert len(out) == 1 and out[0]["name"] == "故宫"


def test_validate_tags_null_tolerated():
    good = {"name": "故宫", "city": "北京", "lat": 39.9, "lng": 116.4,
            "rating": 4.8, "price_tier": 2, "description": "紫禁城。", "tags": ["历史"]}
    bad = dict(good, name="tags空", tags=None)
    out = generate.validate_pois("北京", [good, bad])
    assert len(out) == 2
    assert out[1]["tags"] == []


def test_generate_pois_null_tolerated():
    """pois: null 不得崩溃，按空列表处理（T4-F3 回归保持）。"""
    fake = FakeProvider(json_responses={"四川": {"province": "四川", "pois": None}})
    assert generate.generate_province(fake, "四川") == []  # type: ignore[arg-type]
```

`backend/tests/test_ingest.py` 更新（CORPUS_LINES 加 province、restaurant/spa 行不再有效——只有 attraction 有效；新校验断言）：

```python
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
```

`backend/tests/fixtures/sample_pois.jsonl` 整文件替换为（**只含景点 + province 字段**，Task 3 的检索测试基于此数据）：

```
{"name": "故宫博物院", "province": "北京", "city": "北京", "category": "attraction", "lat": 39.9163, "lng": 116.3972, "rating": 4.8, "price_tier": 2, "description": "明清两代皇宫，世界最大木结构建筑群，需提前预约。", "tags": ["历史", "预约"]}
{"name": "八达岭长城", "province": "北京", "city": "北京", "category": "attraction", "lat": 40.3601, "lng": 116.0124, "rating": 4.7, "price_tier": 2, "description": "万里长城最著名段落，好汉坡。", "tags": ["历史", "徒步"]}
{"name": "广州塔", "province": "广东", "city": "广州", "category": "attraction", "lat": 23.1066, "lng": 113.3245, "rating": 4.6, "price_tier": 3, "description": "珠江畔地标，夜景灯光秀。", "tags": ["夜景", "地标"]}
{"name": "白云山", "province": "广东", "city": "广州", "category": "attraction", "lat": 23.1800, "lng": 113.2900, "rating": 4.4, "price_tier": 1, "description": "羊城第一秀，城市绿肺。", "tags": ["自然", "登山"]}
{"name": "丹霞山", "province": "广东", "city": "韶关", "category": "attraction", "lat": 25.0200, "lng": 113.7500, "rating": 4.7, "price_tier": 2, "description": "世界自然遗产，丹霞地貌命名地。", "tags": ["自然", "世界遗产"]}
{"name": "世界之窗", "province": "广东", "city": "深圳", "category": "attraction", "lat": 22.5340, "lng": 113.9740, "rating": 4.3, "price_tier": 3, "description": "浓缩世界景观的主题公园。", "tags": ["主题公园", "亲子"]}
{"name": "宽窄巷子", "province": "四川", "city": "成都", "category": "attraction", "lat": 30.67, "lng": 104.06, "rating": 4.6, "price_tier": 1, "description": "老成都街区，小吃与茶馆集中。", "tags": ["老街", "小吃"]}
```

`backend/tests/test_vector_store.py` 更新：现有用例保持，新增 province 断言（读该文件后最小补充：查询返回的 dict 含 `province` 键、`query` 支持 `province` 过滤参数）。

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_generate.py tests/test_ingest.py tests/test_vector_store.py -v`
Expected: FAIL（新签名不存在、fixture 校验不通过等）

- [ ] **Step 3: Write the implementation**

`backend/app/rag/generate.py` 重写（删除 CITIES/CITY_EN/CITY_COORDS 硬编码，改为基于 province_cities）：

```python
"""POI 语料生成：DeepSeek 按省份模板批量生成（一次一省，JSON 模式）。

产物是 backend/data/poi_corpus.jsonl，数据为 **AI 生成示例数据，
坐标仅供参考**（README 与前端展示均注明）。只生成景点（attraction）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from app.llm.deepseek import DeepSeekProvider
from app.rag.province_cities import PROVINCES, city_coord

# 34 省遍历顺序（语料生成与断言基准）
PROVINCE_ORDER = [
    "北京", "上海", "天津", "重庆",
    "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东",
    "广西", "海南", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
    "台湾", "香港", "澳门",
]

# 城市 → 拼音（全部 poi_cities 城市，动态生成；poi_id 与别名表共用）
CITY_EN: dict[str, str] = {
    city: pinyin
    for d in PROVINCES.values()
    for city, (pinyin, _coord) in d["poi_cities"].items()
}

VALID_TIERS = {1, 2, 3, 4}

GENERATE_SYSTEM_PROMPT = """你是中国旅游 POI 数据生成器。为指定省份生成著名旅游景点条目（AI 生成示例数据，坐标仅供参考，要落在对应城市市中心周边合理范围）。
只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{"province": "省份名", "pois": [
  {"name": "中文名", "city": "景点所在城市（必须是给定城市清单中的城市）",
   "lat": 纬度, "lng": 经度, "rating": 3.5到5.0一位小数,
   "price_tier": 1到4整数（门票价位）, "description": "50字以内，真实、信息密度高",
   "tags": ["2-4个标签，如 历史/夜景/亲子/自然/世界遗产"]}
]}
数量要求：共 4-6 个景点，分布在给定城市清单中（每城 1-3 个）。只生成景点，不要餐厅/酒店。"""


def generate_province(provider: DeepSeekProvider, province: str) -> list[dict]:
    """调用一次 DeepSeek 生成一省景点，返回校验后的条目（含 province/city 字段）。"""
    poi_cities = PROVINCES[province]["poi_cities"]
    cities_text = "、".join(poi_cities)
    messages = [
        {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"请为「{province}」生成著名景点数据。可选城市：{cities_text}（每城 1-3 个）。"
            f"城市中心坐标：{json.dumps({c: c2 for c, (_p, c2) in poi_cities.items()}, ensure_ascii=False)}。"
            "所有条目坐标必须在对应城市中心 ±2 度范围内。只输出 JSON。"
        )},
    ]
    raw = provider.chat_json(messages)
    pois = (raw.get("pois") or []) if isinstance(raw, dict) else []
    return validate_pois(province, pois)


def validate_pois(province: str, pois: list[dict]) -> list[dict]:
    """字段/城市/类别/评分/价位/坐标校验；非法条目丢弃。"""
    poi_cities = PROVINCES[province]["poi_cities"]
    out = []
    for p in pois:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name", "")).strip()
        city = str(p.get("city", "")).strip()
        if not name or city not in poi_cities:
            continue  # 城市必须在本省 poi_cities 内
        if p.get("category", "attraction") != "attraction":
            continue  # 语料只存景点
        try:
            lat, lng = float(p["lat"]), float(p["lng"])
            rating = float(p["rating"])
            tier = int(p["price_tier"])
        except (KeyError, TypeError, ValueError):
            continue
        clat, clng = city_coord(province, city)
        if not (3.5 <= rating <= 5.0 and tier in VALID_TIERS):
            continue
        if abs(lat - clat) > 2.0 or abs(lng - clng) > 2.0:
            continue  # 坐标越界丢弃
        desc = str(p.get("description") or "").strip()
        if not desc:
            continue
        tags_raw = p.get("tags") or []
        if isinstance(tags_raw, str):
            tags_raw = [tags_raw]
        tags = [str(t).strip() for t in tags_raw if str(t).strip()][:4]
        out.append({
            "poi_id": "", "province": province, "city": city, "name": name,
            "category": "attraction", "lat": lat, "lng": lng, "rating": rating,
            "price_tier": tier, "description": desc, "tags": tags,
        })
    return out


def default_corpus_path() -> Path:
    return Path(os.environ.get("POI_CORPUS_PATH", Path(__file__).resolve().parents[2] / "data" / "poi_corpus.jsonl"))


def main() -> int:
    provider = DeepSeekProvider(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
    )
    out_path = default_corpus_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with out_path.open("w", encoding="utf-8") as f:
        for province in PROVINCE_ORDER:
            pois = generate_province(provider, province)
            for p in pois:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
            total += len(pois)
            print(f"{province}: {len(pois)} 条")
    print(f"完成：{total} 条 → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`backend/app/rag/ingest.py` 更新：

```python
"""POI 语料入库：读取 JSONL → 校验 → 生成 poi_id → 向量化 → Chroma upsert。

用法：python -m app.rag.ingest
（前置：python -m app.rag.download_model 下载 BGE 模型）
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from app.rag.embeddings import Embedder
from app.rag.generate import default_corpus_path
from app.rag.province_cities import PROVINCES, city_coord
from app.rag.vector_store import VectorStore

VALID_CATEGORIES = {"attraction"}


def load_corpus(jsonl_path: str | Path) -> list[dict]:
    """读取语料 JSONL：校验（省份/城市/类别/坐标 ±2°）+ 生成 poi_id（{城市拼音}-{序号:03d}）。"""
    pois: list[dict] = []
    with Path(jsonl_path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                p = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(p, dict):
                continue
            province = p.get("province")
            city = p.get("city")
            if (
                province not in PROVINCES
                or city not in PROVINCES[province]["poi_cities"]
                or p.get("category") not in VALID_CATEGORIES
            ):
                continue
            try:
                lat, lng = float(p["lat"]), float(p["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            clat, clng = city_coord(province, city)
            if abs(lat - clat) > 2.0 or abs(lng - clng) > 2.0:
                continue  # 坐标越界丢弃（语料可能被手工编辑，二次校验）
            p["province"] = province
            p["city"] = city
            p["category"] = "attraction"
            pois.append(p)
    counts: dict[str, int] = {}
    for p in pois:
        key = p["city"]
        counts[key] = counts.get(key, 0) + 1
        p["poi_id"] = f"{PROVINCES[p['province']]['poi_cities'][key][0]}-{counts[key]:03d}"
    return pois


def run_ingest(jsonl_path: str | Path, store: VectorStore) -> int:
    """读取 + 入库，返回入库条数。"""
    pois = load_corpus(jsonl_path)
    return store.upsert_pois(pois)


def default_chroma_dir() -> Path:
    return Path(os.environ.get("CHROMA_PERSIST_DIR", Path(__file__).resolve().parents[2] / "data" / "chroma"))


def main() -> int:
    from app.rag.download_model import ensure_model, default_model_dir

    model_path = ensure_model(default_model_dir())
    print(f"加载 BGE: {model_path}")
    embedder = Embedder(model_path)
    store = VectorStore(str(default_chroma_dir()), embedder)
    corpus = default_corpus_path()
    n = run_ingest(str(corpus), store)
    print(f"入库完成：{n} 条，库内总数 {store.count()} → {default_chroma_dir()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`backend/app/rag/vector_store.py` 更新（metadata 加 province、where 支持 province、docstring 更新）：

```python
    def _doc_text(p: dict) -> str:
        tags = "、".join(p.get("tags", []))
        return (f"{p['name']}。{p.get('description', '')}。标签：{tags}。"
                f"类别：{p['category']}。省份：{p.get('province', '')}。城市：{p['city']}")

    def _meta(p: dict) -> dict:
        return {
            "poi_id": p["poi_id"], "province": p.get("province", ""), "city": p["city"],
            "name": p["name"], "category": p["category"], "rating": float(p["rating"]),
            "price_tier": int(p["price_tier"]), "lat": float(p["lat"]),
            "lng": float(p["lng"]), "description": p.get("description", ""),
            "tags_str": ",".join(p.get("tags", [])),
        }
```

`_poi_dict` 增 `"province"`；`_where` 改为支持 `province`（三元组过滤）：`_where(city=None, province=None, category=None)` 用 `$and` 组合非 None 条件；`query()`/`get_all()` 签名加 `province` 参数（默认 None，`query` 中 `where=self._where(city, province, category)`）。

`backend/tests/test_vector_store.py`：读现有文件后最小修改——`_poi` helper 加 province 字段；新增 `test_query_by_province`（查询 province="广东" 返回 4 条且仅含广东景点）与 `test_poi_dict_contains_province`。

- [ ] **Step 4: Run all tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/ -v`
Expected: 全绿（test_retriever.py 的旧断言可能因 fixture 变化失败——**预期内**，Task 3 统一重写该文件；若失败项仅限 test_retriever 且属于"旧 fixture 断言"，则先临时跳过：在 test_retriever.py 首行加 `pytestmark = pytest.mark.skip(reason="Task 3 重写")` 并在 Task 3 移除；其余测试必须全绿）

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/generate.py backend/app/rag/ingest.py backend/app/rag/vector_store.py backend/tests/fixtures/sample_pois.jsonl backend/tests/test_generate.py backend/tests/test_ingest.py backend/tests/test_vector_store.py backend/tests/test_retriever.py
git commit -m "refactor: province-template corpus generation, attraction-only ingest, province metadata

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 三级粒度检索（normalize_region + search_pois fallback）

**Files:**
- Modify: `backend/app/rag/retriever.py`
- Test: `backend/tests/test_retriever.py`（整文件重写，去掉 Task 2 的 skip 标记）

**Interfaces:**
- Consumes: Task 1 的 `PROVINCE_ALIASES` / `CITY_TO_PROVINCE`；Task 2 的 `CITY_EN`
- Produces（后续任务依赖的精确签名）:
  - `normalize_region(name: str) -> tuple[str | None, str | None]` —— (省份简称, 城市名)；先城市后省份匹配（含拼音/别名）；都无返回 (None, None)
  - `search_pois(name: str, *, query: str | None = None, k: int = 8) -> list[dict]` —— **三级 fallback**：name 归一为城市 → 该市语义检索（query 空按 rating 降序）；归一为省（或城市不在库，经 CITY_TO_PROVINCE 转省）→ 全省景点按 rating 降序；无法归一 → []
  - `get_poi(poi_id: str) -> dict | None`（不变）
  - `search_nearby(lat, lng, *, category=None, radius_km=3.0, k=5)`（保留；category 参数兼容，省范围逻辑 M5 调整）

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_retriever.py -v`
Expected: FAIL（normalize_region 不存在等）

- [ ] **Step 3: Write the implementation** — 重写 `backend/app/rag/retriever.py`

```python
"""RAG 检索对外接口（Researcher 依赖注入点）。

- normalize_region：省/城市名（中文、别名、拼音）→ (省份简称, 城市名 | None)
- search_pois：三级粒度 fallback —— 库内城市→该市；库外城市→所在省；直接省名→全省
- search_nearby：同省候选 + haversine 距离排序（数据量小，全量计算）
- get_store：惰性单例（CHROMA_PERSIST_DIR + 真实 BGE）；set_store 供测试注入
"""
from __future__ import annotations

import math

from app.rag.generate import CITY_EN
from app.rag.province_cities import CITY_TO_PROVINCE, PROVINCE_ALIASES
from app.rag.vector_store import VectorStore

# 城市别名（中文 + 拼音，大小写不敏感）→ 城市名
_CITY_ALIASES: dict[str, str] = {c: c for c in CITY_EN}
_CITY_ALIASES.update({en: c for c, en in CITY_EN.items()})

_store: VectorStore | None = None


def set_store(store: VectorStore | None) -> None:
    """测试注入点：替换全局检索存储（FakeEmbedder 版）。"""
    global _store
    _store = store


def get_store() -> VectorStore:
    """惰性单例；首次调用创建（CHROMA_PERSIST_DIR + 真实 BGE）。

    模型未下载时抛 RuntimeError 提示先执行 `python -m app.rag.download_model`——
    不在服务进程内触发联网下载（避免请求挂起），下载是显式 CLI 步骤。
    """
    global _store
    if _store is None:
        from app.rag.download_model import default_model_dir
        from app.rag.embeddings import Embedder
        from app.rag.ingest import default_chroma_dir

        model_path = default_model_dir()
        if not (model_path.exists() and any(model_path.iterdir())):
            raise RuntimeError(
                f"BGE 模型未就绪：{model_path}。请先运行 python -m app.rag.download_model"
            )
        embedder = Embedder(str(model_path))
        _store = VectorStore(str(default_chroma_dir()), embedder)
    return _store


def normalize_region(name: str) -> tuple[str | None, str | None]:
    """归一为 (省份简称, 城市名)；城市优先（先匹配城市别名，再匹配省别名）。

    返回示例：("广东", "广州") / ("广东", None) / (None, None)。
    """
    key = name.strip().lower()
    city = _CITY_ALIASES.get(key)
    if city is not None:
        return CITY_TO_PROVINCE[city], city
    province = PROVINCE_ALIASES.get(key)
    if province is not None:
        return province, None
    return None, None


def _resolve(name: str) -> tuple[str | None, str | None]:
    """三级 fallback 决策：城市在库返回 (province, city)；城市不在库返回 (province, None)（全省兜底）。"""
    province, city = normalize_region(name)
    if province is None:
        return None, None
    if city is None:
        return province, None
    if city in CITY_EN:  # 城市在语料中（有拼音即景点城市）
        return province, city
    return province, None  # 库外城市 → 所在省兜底


def search_pois(
    name: str,
    *,
    query: str | None = None,
    k: int = 8,
) -> list[dict]:
    """三级粒度检索：库内城市→该市；库外城市/直接省名→全省。"""
    province, city = _resolve(name)
    if province is None:
        return []
    return get_store().query(query or "", city=city, province=province, k=k)


def get_poi(poi_id: str) -> dict | None:
    """按 poi_id 取 POI；不存在返回 None。"""
    for p in get_store().get_all():
        if p["poi_id"] == poi_id:
            return p
    return None


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点球面距离（km）。"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def search_nearby(
    lat: float,
    lng: float,
    *,
    category: str | None = None,
    radius_km: float = 3.0,
    k: int = 5,
) -> list[dict]:
    """候选 + 距离过滤排序的"周边"检索（数据量小，全量计算即可）。"""
    candidates = [p for p in get_store().get_all(category=category) if p.get("lat") is not None]
    scored = []
    for p in candidates:
        d = _haversine(lat, lng, float(p["lat"]), float(p["lng"]))
        if d <= radius_km:
            scored.append((d, p))
    scored.sort(key=lambda item: item[0])
    return [p for _, p in scored[:k]]
```

注意：`VectorStore.query` 在 Task 2 已支持 `province` 参数（where 组合）。`get_all(category=...)` 签名不变。

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/ -v`
Expected: 全绿（含 Task 2 的 skip 标记移除——本任务整文件重写 test_retriever.py，自然移除）

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/retriever.py backend/tests/test_retriever.py
git commit -m "feat: 3-tier granularity retrieval (province / in-KB city / out-of-KB city fallback)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Researcher 节点（检索 + 天气 + LLM 推荐要点）

**Files:**
- Create: `backend/app/agents/researcher.py`
- Test: `backend/tests/test_researcher.py`

**Interfaces:**
- Consumes: Task 3 的 `normalize_region` / `search_pois`；`app.tools.weather_api.get_weather`；`app.rag.province_cities.city_coord`；`app.events.publish`
- Produces（后续任务依赖）:
  - `researcher_node(state, llm, *, weather_fn, search_pois_fn, normalize_region_fn) -> dict`
  - state 写入：`candidates`（Annotated list 累加；元素 = POI dict + `reason` 键）、`weather`（list，整体覆盖）、`region_resolved`（bool）
  - FakeProvider 匹配键：用户提示词含 `"推荐"` 字样 → 响应 `{"recommendations": [{"poi_id", "reason"}]}`

**流程**：publish start → profile.destination → normalize_region → (None, None) 时 `region_resolved=False` + 空 candidates/weather 提前返回 → 否则 search_pois 取候选（query=偏好 or None, k=8）→ 候选非空时 LLM 生成推荐要点（`chat_json`，输入候选 JSON，输出 recommendations）→ 合并 reason 进 candidates → 天气坐标 = 候选第一条坐标，无候选则 `city_coord(province, None)` → weather_fn → publish done → 返回。

```python
"""Researcher 研究员：RAG 三级粒度检索景点候选 + 实时天气 + LLM 推荐要点。

LLM 只产出结构化 JSON（recommendations 引用 poi_id）；candidates 元素为
POI dict + reason（推荐理由），供 Planner 消费。
"""
from __future__ import annotations

import json
from collections.abc import Callable

from app import events
from app.llm.deepseek import DeepSeekProvider
from app.rag.province_cities import city_coord
from app.rag.retriever import normalize_region as _default_normalize_region
from app.rag.retriever import search_pois as _default_search_pois
from app.tools.weather_api import get_weather as _default_weather

RESEARCHER_SYSTEM_PROMPT = """你是智能旅行助手的"研究员"。根据候选景点列表，为每条候选生成一句话推荐理由（10-20 字，如 亲子友好/夜景绝佳/世界遗产）。
只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{"recommendations": [
  {"poi_id": "候选列表中的 id，必须引用", "reason": "一句话推荐理由"}
]}
- 最多选 5 条最贴合用户偏好的候选；偏好不明确时选评分最高的"""


def researcher_node(
    state: dict,
    llm: DeepSeekProvider,
    *,
    weather_fn: Callable = _default_weather,
    search_pois_fn: Callable = _default_search_pois,
    normalize_region_fn: Callable = _default_normalize_region,
) -> dict:
    events.publish({"type": "agent_status", "data": {"agent": "researcher", "status": "start"}})
    profile: dict = state.get("profile", {})
    destination = str(profile.get("destination", "") or "")
    province, city = normalize_region_fn(destination)
    if province is None:
        events.publish({"type": "agent_status", "data": {"agent": "researcher", "status": "done"}})
        return {"candidates": [], "weather": [], "region_resolved": False}

    prefs = " ".join(profile.get("preferences", []))
    candidates = search_pois_fn(destination, query=prefs or None, k=8)

    if candidates:
        messages = [
            {"role": "system", "content": RESEARCHER_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"用户偏好：{prefs or '未明确'}。\n候选景点："
                f"{json.dumps([{'poi_id': p['poi_id'], 'name': p['name'], 'city': p['city'], "
                f"'rating': p['rating'], 'description': p['description']} for p in candidates], ensure_ascii=False)}\n"
                "请按 schema 输出推荐要点 JSON（标记词：推荐要点JSON）。"
            )},
        ]
        try:
            recs = llm.chat_json(messages)
        except (AssertionError, ValueError, KeyError, TypeError):
            recs = {}
        reasons = {r.get("poi_id"): str(r.get("reason", "")) for r in (recs.get("recommendations") or []) if isinstance(r, dict)}
        for p in candidates:
            p["reason"] = reasons.get(p["poi_id"], "")

    lat, lng = (float(candidates[0]["lat"]), float(candidates[0]["lng"])) if candidates else city_coord(province, city)
    weather = weather_fn(lat, lng, days=profile.get("duration_days", 3))
    events.publish({"type": "agent_status", "data": {"agent": "researcher", "status": "done"}})
    return {"candidates": candidates, "weather": weather, "region_resolved": True}
```

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_researcher.py`

```python
from app.agents import researcher

from conftest import FakeProvider, fake_weather

CANDIDATES = [
    {"poi_id": "guangzhou-001", "province": "广东", "city": "广州", "name": "广州塔",
     "category": "attraction", "lat": 23.1066, "lng": 113.3245, "rating": 4.6,
     "price_tier": 3, "description": "珠江畔地标。", "tags": ["夜景"]},
    {"poi_id": "guangzhou-002", "province": "广东", "city": "广州", "name": "白云山",
     "category": "attraction", "lat": 23.18, "lng": 113.29, "rating": 4.4,
     "price_tier": 1, "description": "城市绿肺。", "tags": ["自然"]},
]


def _fake():
    return FakeProvider(json_responses={"推荐要点JSON": {
        "recommendations": [
            {"poi_id": "guangzhou-001", "reason": "夜景绝佳，适合晚上登塔"},
        ],
    }})


def _state():
    return {
        "messages": [{"role": "user", "content": "10月去广州玩3天，预算8000，喜欢美食"}],
        "phase": "planning",
        "profile": {"destination": "广州", "duration_days": 3, "start_date": "2026-10-01",
                    "budget_cny": 8000, "travelers": 2, "preferences": ["美食"]},
    }


def _normalize(name):
    return ("广东", "广州") if "广州" in name else (None, None)


def _search(name, *, query=None, k=8):
    return list(CANDIDATES) if "广州" in name else []


def _kwargs():
    return {"weather_fn": fake_weather, "search_pois_fn": _search, "normalize_region_fn": _normalize}


def test_researcher_candidates_weather_reason():
    fake = _fake()
    out = researcher.researcher_node(_state(), fake, **_kwargs())  # type: ignore[arg-type]
    assert out["region_resolved"] is True
    assert [p["poi_id"] for p in out["candidates"]] == ["guangzhou-001", "guangzhou-002"]
    assert out["candidates"][0]["reason"] == "夜景绝佳，适合晚上登塔"
    assert out["candidates"][1]["reason"] == ""  # 未推荐 → 空理由
    assert out["weather"] and out["weather"][0]["source"] == "open-meteo"


def test_researcher_unknown_region():
    out = researcher.researcher_node(_state(), FakeProvider(), **_kwargs())  # type: ignore[arg-type]
    assert out["region_resolved"] is False
    assert out["candidates"] == [] and out["weather"] == []


def test_researcher_prompt_contains_candidates():
    fake = _fake()
    researcher.researcher_node(_state(), fake, **_kwargs())  # type: ignore[arg-type]
    prompt = fake.calls[0][-1]["content"]
    assert "广州塔" in prompt and "poi_id" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_researcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agents.researcher'`

- [ ] **Step 3: Write the implementation**（上文代码逐字使用；`llm.chat_json` 异常捕获用 `except (ValueError, KeyError, TypeError):` 覆盖 T1-F1 家族裸异常）

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/ -v`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/researcher.py backend/tests/test_researcher.py
git commit -m "feat: researcher node — 3-tier RAG retrieval + weather + LLM recommendations

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Budget 预算官节点（LLM 分配 + 确定性缩放兜底）

**Files:**
- Create: `backend/app/agents/budget.py`
- Test: `backend/tests/test_budget.py`

**Interfaces:**
- Consumes: `app.events.publish`
- Produces（后续任务依赖）:
  - `budget_node(state, llm) -> dict`
  - `BUDGET_CATEGORIES: list[str] = ["住宿", "交通", "餐饮", "门票", "其他"]`
  - `format_budget(plan: dict) -> str`（预算表 markdown；items 空返回 ""）
  - state 写入：`budget_plan`（整体覆盖）：`{"items": [{"category", "amount", "note"}], "total": int, "checked": True, "scaled": bool}`
  - FakeProvider 匹配键：提示词含 `"预算"` → `{"items": [{"category": "住宿", "amount": 3200, "note": "中档酒店"}], "total": 8000}`

**预算逻辑（确定性，逐字实现）**：
1. `profile["budget_cny"]` 缺失/非正数 → `budget_plan = {"items": [], "total": None, "checked": False, "scaled": False, "note": "未提供总预算"}`（提前返回，不调 LLM）
2. LLM 调用（输入 profile + 总预算 + 天数）→ 解析 items；`_clean_items(items, budget_cny)`：
   - 丢弃 category ∉ BUDGET_CATEGORIES、amount 非正整数的条目
   - 类别去重（保留首次出现）
   - LLM 异常 / items 空 → `_default_items(budget_cny)`（确定性兜底：住宿 40% / 交通 20% / 餐饮 25% / 门票 15% / 其他=余量，保证 sum == budget_cny）
3. 缩放：`total = sum(amounts)`；total > budget_cny → 等比缩放（round 后尾差收齐，最后一项 = budget_cny - 已累计），`scaled=True`；否则保持原值
4. 产出 budget_plan（total 用重算值，不信 LLM 的 total 字段）

```python
"""Budget 预算官：按总预算分配类别额度，产出预算表。

LLM 只产出结构化 JSON（items）；确定性兜底保证 sum(items) <= budget_cny：
- 缩放：总超预算时等比缩放，尾差收齐
- 兜底：LLM 失败/空 items 时按固定比例分配
"""
from __future__ import annotations

from app import events
from app.llm.deepseek import DeepSeekProvider

BUDGET_CATEGORIES = ["住宿", "交通", "餐饮", "门票", "其他"]

BUDGET_SYSTEM_PROMPT = """你是智能旅行助手的"预算官"。根据用户总预算、天数与偏好，把预算分配到固定类别。
只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{"items": [
  {"category": "住宿|交通|餐饮|门票|其他", "amount": 金额整数, "note": "一句话说明，10 字内"}
]}
规则：
- 类别必须取自：住宿、交通、餐饮、门票、其他，每个类别最多一条
- 总金额不得超过预算上限；住宿占比通常 30-45%，餐饮 20-30%
- 金额用整数（元）"""

DEFAULT_WEIGHTS: list[tuple[str, float]] = [
    ("住宿", 0.40), ("交通", 0.20), ("餐饮", 0.25), ("门票", 0.15),
]


def _default_items(budget_cny: int) -> list[dict]:
    """确定性兜底分配：按固定比例，尾差归"其他"，保证 sum == budget_cny。"""
    items = []
    used = 0
    for name, weight in DEFAULT_WEIGHTS:
        amount = round(budget_cny * weight)
        items.append({"category": name, "amount": amount, "note": "默认比例分配"})
        used += amount
    items.append({"category": "其他", "amount": budget_cny - used, "note": "机动余量"})
    return items


def _clean_items(items: list, budget_cny: int) -> list[dict]:
    """清洗 LLM 输出：非法类别丢弃、金额取正整、类别去重；清洗后空 → 兜底。"""
    seen: set[str] = set()
    out: list[dict] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        category = str(it.get("category", "")).strip()
        if category not in BUDGET_CATEGORIES or category in seen:
            continue
        try:
            amount = int(it["amount"])
        except (KeyError, TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        seen.add(category)
        out.append({"category": category, "amount": amount,
                    "note": str(it.get("note", "") or "").strip()[:20]})
    return out or _default_items(budget_cny)


def _scale(items: list[dict], budget_cny: int) -> tuple[list[dict], bool]:
    """等比缩放到总和不超预算；最后一项收尾差。返回 (items, scaled)。"""
    total = sum(it["amount"] for it in items)
    if total <= budget_cny:
        return items, False
    scale = budget_cny / total
    scaled = []
    used = 0
    for i, it in enumerate(items):
        if i == len(items) - 1:
            amount = budget_cny - used  # 尾差收齐
        else:
            amount = round(it["amount"] * scale)
            used += amount
        scaled.append({"category": it["category"], "amount": amount, "note": it["note"]})
    return scaled, True


def format_budget(plan: dict) -> str:
    """预算表 markdown（确定性）；items 空返回空串。"""
    items = plan.get("items") or []
    if not items:
        return ""
    lines = ["## 预算分配", "", "| 类别 | 金额（元） | 说明 |", "|---|---|---|"]
    for it in items:
        lines.append(f"| {it['category']} | {it['amount']} | {it.get('note', '')} |")
    total = plan.get("total", sum(it["amount"] for it in items))
    mark = "（已按预算上限缩放）" if plan.get("scaled") else ""
    lines.append(f"| **合计** | **{total}** | {mark} |")
    return "\n".join(lines)


def budget_node(state: dict, llm: DeepSeekProvider) -> dict:
    events.publish({"type": "agent_status", "data": {"agent": "budget", "status": "start"}})
    profile: dict = state.get("profile", {})
    budget_cny = profile.get("budget_cny")
    if not isinstance(budget_cny, (int, float)) or budget_cny <= 0:
        events.publish({"type": "agent_status", "data": {"agent": "budget", "status": "done"}})
        return {"budget_plan": {"items": [], "total": None, "checked": False,
                                "scaled": False, "note": "未提供总预算"}}

    import json

    budget_cny = int(budget_cny)
    messages = [
        {"role": "system", "content": BUDGET_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"画像：{json.dumps(profile, ensure_ascii=False)}\n"
            f"总预算上限：{budget_cny} 元，出行 {profile.get('duration_days', 3)} 天。\n"
            "请按 schema 输出预算分配 JSON（标记词：预算分配JSON）。"
        )},
    ]
    try:
        parsed = llm.chat_json(messages)
        items = _clean_items(parsed.get("items"), budget_cny)
    except (AssertionError, ValueError, KeyError, TypeError):
        items = _default_items(budget_cny)

    items, scaled = _scale(items, budget_cny)
    events.publish({"type": "agent_status", "data": {"agent": "budget", "status": "done"}})
    return {"budget_plan": {
        "items": items,
        "total": sum(it["amount"] for it in items),
        "checked": True, "scaled": scaled,
    }}
```

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_budget.py`

```python
import pytest

from app.agents import budget

from conftest import FakeProvider


def _state(budget_cny=8000, days=3):
    return {
        "messages": [], "phase": "planning",
        "profile": {"destination": "广州", "duration_days": days, "start_date": "2026-10-01",
                    "budget_cny": budget_cny, "travelers": 2, "preferences": ["美食"]},
    }


def test_budget_llm_allocation():
    fake = FakeProvider(json_responses={"预算分配JSON": {
        "items": [{"category": "住宿", "amount": 3200, "note": "中档酒店"},
                  {"category": "餐饮", "amount": 2400, "note": "粤菜为主"},
                  {"category": "交通", "amount": 1200, "note": "高铁"},
                  {"category": "门票", "amount": 800, "note": "塔+白云山"},
                  {"category": "其他", "amount": 400, "note": "机动"}],
        "total": 8000,
    }})
    out = budget.budget_node(_state(), fake)  # type: ignore[arg-type]
    plan = out["budget_plan"]
    assert plan["checked"] is True and plan["scaled"] is False
    assert plan["total"] == 8000
    assert {it["category"] for it in plan["items"]} == {"住宿", "交通", "餐饮", "门票", "其他"}


def test_budget_scales_when_over_limit():
    """LLM 给出 12000 > 8000 → 等比缩放到 8000，尾差收齐。"""
    fake = FakeProvider(json_responses={"预算分配JSON": {
        "items": [{"category": "住宿", "amount": 6000, "note": "x"},
                  {"category": "餐饮", "amount": 6000, "note": "x"}],
    }})
    plan = budget.budget_node(_state(8000), fake)["budget_plan"]  # type: ignore[arg-type]
    assert plan["scaled"] is True and plan["total"] == 8000
    assert sum(it["amount"] for it in plan["items"]) == 8000


def test_budget_default_fallback():
    """LLM 失败（未配置响应）→ 确定性比例分配，总和精确等于预算。"""
    plan = budget.budget_node(_state(8000), FakeProvider())["budget_plan"]  # type: ignore[arg-type]
    assert plan["checked"] is True
    assert plan["total"] == 8000
    cats = [it["category"] for it in plan["items"]]
    assert cats == ["住宿", "交通", "餐饮", "门票", "其他"]
    amounts = {it["category"]: it["amount"] for it in plan["items"]}
    assert amounts["住宿"] == 3200 and amounts["交通"] == 1600 and amounts["餐饮"] == 2000
    assert amounts["门票"] == 1200 and amounts["其他"] == 0


def test_budget_cleans_bad_categories():
    """非法类别与重复类别被丢弃，剩余为空时走兜底。"""
    fake = FakeProvider(json_responses={"预算分配JSON": {
        "items": [{"category": "购物", "amount": 500, "note": "非法类别"},
                  {"category": "住宿", "amount": 3000, "note": "ok"},
                  {"category": "住宿", "amount": 999, "note": "重复类别"}],
    }})
    plan = budget.budget_node(_state(8000), fake)["budget_plan"]  # type: ignore[arg-type]
    assert [it["category"] for it in plan["items"]] == ["住宿"]
    assert plan["items"][0]["amount"] == 3000


def test_budget_missing_budget_skips():
    out = budget.budget_node(_state(None), FakeProvider())  # type: ignore[arg-type]
    assert out["budget_plan"]["checked"] is False
    assert "未提供总预算" in out["budget_plan"]["note"]


def test_format_budget_table():
    plan = {"items": [{"category": "住宿", "amount": 3200, "note": "中档酒店"}],
            "total": 3200, "scaled": False}
    text = budget.format_budget(plan)
    assert "## 预算分配" in text and "| 住宿 | 3200 |" in text and "| **合计** | **3200** |" in text


def test_format_budget_empty():
    assert budget.format_budget({"items": [], "total": None, "scaled": False}) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_budget.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agents.budget'`

- [ ] **Step 3: Write the implementation**（上文代码逐字使用）

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/ -v`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/budget.py backend/tests/test_budget.py
git commit -m "feat: budget node — LLM allocation with deterministic scaling fallback

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Supervisor 主管节点（LLM 结构化汇总 + 确定性格式化）

**Files:**
- Create: `backend/app/agents/supervisor.py`
- Test: `backend/tests/test_supervisor.py`

**Interfaces:**
- Consumes: Task 5 的 `format_budget`；`app.agents.planner.format_itinerary`；`app.events.publish`
- Produces（后续任务依赖）:
  - `supervisor_node(state, llm) -> dict`（写入 `supervisor_summary` + `last_reply` + `phase: "answered"`）
  - `format_supervisor_reply(itinerary, budget_plan, weather, summary="", tips=None) -> str`
  - FakeProvider 匹配键：提示词含 `"汇总"` → `{"summary": "...", "tips": ["..."]}`

**回复结构（确定性）**：`format_itinerary(itinerary)` + `\n\n` + `format_budget(budget_plan)`（空则省略） + `\n\n**总体建议**：{summary}`（空则省略） + `💡 {tips[i]}` 逐条 + 天气模拟脚注（`any(w["source"] == "simulated" for w in weather)` 时追加 `\n\n_（天气数据暂不可用，已用模拟数据，仅供参考）_`）。LLM 失败 → summary=""、tips=[]，其余照拼。

```python
"""Supervisor 主管：LLM 结构化汇总（summary/tips）+ 确定性拼装最终回复。

LLM 只产出结构化 JSON；last_reply 由 format_supervisor_reply 确定性生成
（行程 markdown + 预算表 markdown + 总体建议 + 提示），遵循 spec 风险对策。
"""
from __future__ import annotations

import json

from app import events
from app.agents.budget import format_budget
from app.agents.planner import format_itinerary
from app.llm.deepseek import DeepSeekProvider

SUPERVISOR_SYSTEM_PROMPT = """你是智能旅行助手的"主管"。查看行程、预算、天气与用户画像，输出整体总结与建议。
只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{"summary": "对行程和预算的整体评价与建议，50 字以内", "tips": ["提示数组，每条 20 字以内，如 天气提醒/预算提醒/预约提醒"]}
规则：
- summary 客观精炼，不要重复行程细节
- tips 1-3 条，优先天气与预算相关"""


def format_supervisor_reply(
    itinerary: dict,
    budget_plan: dict,
    weather: list[dict],
    summary: str = "",
    tips: list[str] | None = None,
) -> str:
    """确定性拼装最终回复：行程 + 预算表 + 总体建议 + 提示 + 天气脚注。"""
    parts = [format_itinerary(itinerary)]
    budget_text = format_budget(budget_plan)
    if budget_text:
        parts.append(budget_text)
    if summary:
        parts.append(f"**总体建议**：{summary}")
    for tip in tips or []:
        if tip.strip():
            parts.append(f"💡 {tip.strip()}")
    reply = "\n\n".join(parts)
    if any(w.get("source") == "simulated" for w in weather):
        reply += "\n\n_（天气数据暂不可用，已用模拟数据，仅供参考）_"
    return reply


def supervisor_node(state: dict, llm: DeepSeekProvider) -> dict:
    events.publish({"type": "agent_status", "data": {"agent": "supervisor", "status": "start"}})
    summary, tips = "", []
    try:
        messages = [
            {"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"画像：{json.dumps(state.get('profile', {}), ensure_ascii=False)}\n"
                f"行程：{json.dumps(state.get('itinerary', {}), ensure_ascii=False)}\n"
                f"预算：{json.dumps(state.get('budget_plan', {}), ensure_ascii=False)}\n"
                f"天气：{json.dumps(state.get('weather', []), ensure_ascii=False)}\n"
                "请按 schema 输出汇总 JSON（标记词：汇总JSON）。"
            )},
        ]
        parsed = llm.chat_json(messages)
        summary = str(parsed.get("summary") or "")[:200].strip()
        tips = [str(t).strip()[:100] for t in (parsed.get("tips") or []) if str(t).strip()][:5]
    except (AssertionError, ValueError, KeyError, TypeError):
        summary, tips = "", []  # LLM 失败 → 确定性兜底拼装

    reply = format_supervisor_reply(
        state.get("itinerary", {}),
        state.get("budget_plan", {}),
        state.get("weather", []),
        summary, tips,
    )
    events.publish({"type": "agent_status", "data": {"agent": "supervisor", "status": "done"}})
    return {"supervisor_summary": {"summary": summary, "tips": tips},
            "last_reply": reply, "phase": "answered"}
```

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_supervisor.py`

```python
from app.agents import supervisor

from conftest import FakeProvider

ITINERARY = {
    "days": [{"day": 1, "title": "广州地标", "weather_note": "晴 24°C",
              "items": [{"time": "19:00", "name": "广州塔", "poi_id": "guangzhou-001", "note": "夜景"}]}],
    "summary": "首日珠江夜景线。", "warnings": [],
}
BUDGET = {
    "items": [{"category": "住宿", "amount": 3200, "note": "中档酒店"}],
    "total": 3200, "checked": True, "scaled": False,
}
WEATHER = [{"date": "2026-10-01", "t_max": 24.0, "t_min": 16.0,
            "condition": "晴", "source": "open-meteo"}]


def _state():
    return {
        "messages": [], "phase": "planning",
        "profile": {"destination": "广州", "duration_days": 3, "budget_cny": 8000},
        "itinerary": ITINERARY, "budget_plan": BUDGET, "weather": WEATHER,
    }


def test_supervisor_reply_contains_all_sections():
    fake = FakeProvider(json_responses={"汇总JSON": {
        "summary": "整体节奏合理，预算充裕。", "tips": ["周三起降温，带外套", "广州塔建议提前预约"],
    }})
    out = supervisor.supervisor_node(_state(), fake)  # type: ignore[arg-type]
    assert out["phase"] == "answered"
    assert out["supervisor_summary"]["summary"] == "整体节奏合理，预算充裕。"
    reply = out["last_reply"]
    assert "第 1 天" in reply          # 行程 markdown
    assert "## 预算分配" in reply      # 预算表 markdown
    assert "**总体建议**" in reply     # summary
    assert "💡" in reply               # tips
    assert "模拟数据" not in reply     # open-meteo 无脚注


def test_supervisor_llm_failure_fallback():
    """LLM 未配置响应（抛异常）→ 纯确定性拼装，行程与预算仍在。"""
    out = supervisor.supervisor_node(_state(), FakeProvider())  # type: ignore[arg-type]
    assert out["supervisor_summary"] == {"summary": "", "tips": []}
    assert "第 1 天" in out["last_reply"]
    assert "## 预算分配" in out["last_reply"]


def test_supervisor_simulated_weather_footnote():
    weather = [{"date": "2026-10-01", "t_max": 24.0, "t_min": 16.0,
                "condition": "晴", "source": "simulated"}]
    state = _state()
    state["weather"] = weather
    out = supervisor.supervisor_node(state, FakeProvider())  # type: ignore[arg-type]
    assert "模拟数据" in out["last_reply"]


def test_format_supervisor_reply_skips_empty_budget():
    text = supervisor.format_supervisor_reply(ITINERARY, {"items": [], "total": None}, WEATHER, "不错", ["带伞"])
    assert "## 预算分配" not in text
    assert "**总体建议**：不错" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_supervisor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agents.supervisor'`

- [ ] **Step 3: Write the implementation**（上文代码逐字使用）

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/ -v`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/supervisor.py backend/tests/test_supervisor.py
git commit -m "feat: supervisor node — LLM structured summary + deterministic reply assembly

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Planner 改造 + 5 节点图装配 + 前端 + 全量测试更新

**Files:**
- Modify: `backend/app/agents/planner.py`（去注入点、消费 state candidates/budget_plan/weather、酒店/餐厅 LLM 生成标注示例、删除天气脚注拼接）
- Modify: `backend/app/agents/analyst.py`（destination 提示词允许省份）
- Modify: `backend/app/state.py`（新增 5 个状态字段）
- Modify: `backend/app/graph.py`（5 节点拓扑 + 并行 fan-out + planner 条件边）
- Modify: `backend/app/api/chat.py`（删除假 supervisor 事件行）
- Modify: `frontend/src/components/AgentProcessPanel.tsx`（AGENT_NAMES +2）
- Test: `backend/tests/test_planner.py`（重写）、`backend/tests/test_graph.py`（重写）、`backend/tests/test_chat.py`（更新 FakeProvider keys）

**Interfaces:**
- Consumes: Task 4 的 `researcher_node`（注入点签名）、Task 5 的 `budget_node`、Task 6 的 `supervisor_node`、Task 2/3 的 RAG 层
- Produces: `build_graph(llm_provider, *, weather_fn, search_pois_fn, normalize_region_fn) -> CompiledStateGraph`；5 节点：analyst / researcher / budget / planner / supervisor

**Planner 新逻辑（重写 planner_node）：**

```python
PLANNER_SYSTEM_PROMPT = """你是智能旅行助手的"行程规划师"。根据用户画像、候选景点、预算约束与天气，生成逐日行程。
只输出 JSON 对象（不要 markdown、不要其他文字），schema：
{
  "days": [
    {
      "day": 1,
      "title": "当日主题，如 广州地标与珠江夜景",
      "weather_note": "当日天气一句话，如 晴 24°C",
      "items": [
        {"time": "09:00", "name": "景点名", "poi_id": "候选列表中的景点 id（景点必须引用）", "note": "为什么去/怎么玩，10-20 字"},
        {"time": "12:30", "name": "餐厅名（示例）", "note": "午餐（示例数据，由你基于常识生成）"}
      ]
    }
  ],
  "summary": "整体行程总结，50 字以内",
  "warnings": ["提示，如 需要提前预约/雨天备选，没有则为空数组"]
}
规则：
- 每天 3-5 项，时间从早到晚；餐饮穿插在景点之间，每天 1-2 餐
- 景点必须从候选景点中选取并引用其 poi_id，不要编造景点
- 酒店与餐厅是示例数据：由你基于目的地常识生成名称，名称后标注（示例），不要填 poi_id
- 住宿按预算约束的每晚住宿预算选档位
- 雨天（condition 含 雨/雪/雷）优先安排室内景点
- 尊重用户偏好标签（美食/购物/文化/自然/亲子），缺偏好时均衡安排
- 天数以 duration_days 为准，不要多排"""
```

`planner_node(state, llm)`（无注入点）：
1. publish start
2. `region_resolved = state.get("region_resolved")`；False → done + 返回 `{"phase": "answered", "itinerary": {}, "last_reply": f"目前暂不支持「{destination}」的行程规划，当前支持全国 34 个省级行政区的著名景点。"}`（图装配中该分支直接 END，不经 supervisor）
3. 读取 `candidates = state.get("candidates", [])`、`budget_plan = state.get("budget_plan", {})`、`weather = state.get("weather", [])`
4. 候选上下文（name/评分/价位/描述/理由）+ 预算约束文本（`json.dumps(budget_plan["items"], ensure_ascii=False)` 原样展示）+ 天气 JSON → chat_json（user 消息末尾**必须包含标记句** `请按 schema 输出行程 JSON（标记词：行程规划JSON），景点条目必须引用候选 POI 的 poi_id。`——FakeProvider 全流程测试按此匹配）
5. 幻觉清洗：**有 poi_id 且不在候选集合 → 丢弃；无 poi_id → 保留（示例餐饮/住宿）**
6. done + 返回 `{"phase": "answered", "itinerary": itinerary, "last_reply": format_itinerary(itinerary)}`——**删除 M2 的天气脚注拼接逻辑（原 planner.py 148-151 行）**：脚注统一由 supervisor 的 `format_supervisor_reply` 输出（否则重复）；last_reply 会被 supervisor 覆盖（正常路径），照写保持单节点可用

`state.py` 新增字段（在现有 5 字段后追加，保持已有字段不动）：

```python
    # M3：Researcher / Budget / Supervisor 产出
    candidates: Annotated[list[dict], operator.add]  # 景点候选 + 推荐理由
    weather: list[dict]               # 逐日天气（Researcher 产出，整体覆盖）
    budget_plan: dict                 # 预算分配（Budget 产出）
    region_resolved: bool             # Researcher 归一化结果（False=未知区域）
    supervisor_summary: dict          # Supervisor 结构化汇总
```

候选文本构建（`build_candidate_context` 保留但改输入）：

```python
def build_candidate_context(candidates: list[dict]) -> str:
    lines = ["候选景点（必须从中选景点并引用 poi_id）:"]
    for p in candidates:
        reason = f"，推荐理由：{p['reason']}" if p.get("reason") else ""
        lines.append(f"- {p['name']}（{p['city']}，评分{p['rating']}，价位档{p['price_tier']}）: {p['description']}{reason}")
    return "\n".join(lines) if lines else "（无候选景点）"
```

**graph.py 重写：**

```python
from functools import partial

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.analyst import analyst_node
from app.agents.budget import budget_node
from app.agents.planner import planner_node
from app.agents.researcher import researcher_node
from app.agents.supervisor import supervisor_node
from app.llm.deepseek import DeepSeekProvider
from app.rag.retriever import normalize_region as _default_normalize_region
from app.rag.retriever import search_pois as _default_search_pois
from app.state import TravelState
from app.tools.weather_api import get_weather as _default_weather


def build_graph(
    llm_provider: DeepSeekProvider,
    *,
    weather_fn=_default_weather,
    search_pois_fn=_default_search_pois,
    normalize_region_fn=_default_normalize_region,
) -> CompiledStateGraph:
    """装配 5 节点图：analyst → ‖researcher‖budget‖ → planner → supervisor → END。

    需求缺失时 analyst 追问后直接 END（等待用户下一轮消息）。
    weather_fn / search_pois_fn / normalize_region_fn 为 Researcher 的依赖注入点
    （测试传 fake 实现，生产用默认真实实现）。"""
    g = StateGraph(TravelState)
    g.add_node("analyst", partial(analyst_node, llm=llm_provider))
    g.add_node("researcher", partial(
        researcher_node, llm=llm_provider,
        weather_fn=weather_fn, search_pois_fn=search_pois_fn,
        normalize_region_fn=normalize_region_fn,
    ))
    g.add_node("budget", partial(budget_node, llm=llm_provider))
    g.add_node("planner", partial(planner_node, llm=llm_provider))
    g.add_node("supervisor", partial(supervisor_node, llm=llm_provider))
    g.set_entry_point("analyst")
    # 并行 fan-out：条件边返回列表 → researcher 与 budget 两个分支同时进入
    g.add_conditional_edges(
        "analyst",
        lambda state: ["researcher", "budget"] if state.get("phase") == "planning" else [END],
        {"researcher": "researcher", "budget": "budget", END: END},
    )
    # join：两条边汇入 planner，两分支都完成后才运行（LangGraph superstep join 语义）
    g.add_edge("researcher", "planner")
    g.add_edge("budget", "planner")
    # planner 未知区域时直接输出降级回复（region_resolved=False），
    # 不走 supervisor——否则 supervisor 会用空行程覆盖降级回复
    g.add_conditional_edges(
        "planner",
        lambda state: END if state.get("region_resolved") is False else "supervisor",
        {"supervisor": "supervisor", END: END},
    )
    g.add_edge("supervisor", END)
    return g.compile()
```

**analyst.py 提示词微调**：`"destination": "目的地中文名（城市或省份，如 广州/成都/广东；未知为 null）"`。

**chat.py**：删除第 30 行 `events.publish({"type": "agent_status", "data": {"agent": "supervisor", "status": "start", "detail": "开始处理"}})`（supervisor 节点现在发真事件）。

**前端**：`AgentProcessPanel.tsx` AGENT_NAMES 改为：

```ts
const AGENT_NAMES: Record<string, string> = {
  analyst: "需求分析师",
  researcher: "研究员",
  budget: "预算官",
  planner: "行程规划师",
  supervisor: "主管",
};
```

**测试更新：**

`test_planner.py` 重写（无注入点；state 带 candidates/budget_plan/weather；提示词断言改）：

```python
import json

from app.agents import planner

from conftest import FakeProvider

CANDIDATES = [
    {"poi_id": "guangzhou-001", "province": "广东", "city": "广州", "name": "广州塔",
     "category": "attraction", "lat": 23.1066, "lng": 113.3245, "rating": 4.6,
     "price_tier": 3, "description": "珠江畔地标。", "tags": ["夜景"], "reason": "夜景绝佳"},
    {"poi_id": "guangzhou-002", "province": "广东", "city": "广州", "name": "白云山",
     "category": "attraction", "lat": 23.18, "lng": 113.29, "rating": 4.4,
     "price_tier": 1, "description": "城市绿肺。", "tags": ["自然"], "reason": ""},
]

ITINERARY = {
    "days": [{"day": 1, "title": "广州地标", "weather_note": "晴 24°C",
              "items": [{"time": "19:00", "name": "广州塔", "poi_id": "guangzhou-001", "note": "夜景"},
                        {"time": "12:30", "name": "点都德（示例）", "note": "午餐"}]}],
    "summary": "OK", "warnings": [],
}

BUDGET_PLAN = {
    "items": [{"category": "住宿", "amount": 3200, "note": "中档酒店"},
              {"category": "餐饮", "amount": 2400, "note": "粤菜"}],
    "total": 8000, "checked": True, "scaled": False,
}

WEATHER = [{"date": "2026-10-01", "t_max": 24.0, "t_min": 16.0, "condition": "晴", "source": "open-meteo"}]


def _fake():
    return FakeProvider(json_responses={"行程": ITINERARY})


def _state():
    return {
        "messages": [{"role": "user", "content": "10月去广州玩3天，预算8000，喜欢美食"}],
        "phase": "planning",
        "profile": {"destination": "广州", "duration_days": 3, "start_date": "2026-10-01",
                    "budget_cny": 8000, "travelers": 2, "preferences": ["美食"]},
        "candidates": CANDIDATES, "budget_plan": BUDGET_PLAN, "weather": WEATHER,
        "region_resolved": True,
    }


def test_planner_produces_reply_and_itinerary():
    fake = _fake()
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert out["phase"] == "answered"
    assert out["itinerary"]["days"][0]["items"][0]["poi_id"] == "guangzhou-001"
    assert out["last_reply"].startswith("## ")


def test_planner_prompt_contains_candidates_budget_weather():
    fake = _fake()
    planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    prompt = fake.calls[0][-1]["content"]
    assert "广州塔" in prompt and "白云山" in prompt     # 候选进上下文
    assert "夜景绝佳" in prompt                          # 推荐理由进上下文
    assert "3200" in prompt                              # 预算约束进上下文
    assert "晴" in prompt                                # 天气进上下文


def test_planner_unknown_region_returns_hint():
    fake = _fake()
    state = _state()
    state["region_resolved"] = False
    state["profile"]["destination"] = "巴黎"
    out = planner.planner_node(state, fake)  # type: ignore[arg-type]
    assert out["phase"] == "answered"
    assert "巴黎" in out["last_reply"]
    assert "暂不支持" in out["last_reply"]
    assert fake.calls == []  # 未知目的地不调用 LLM


def test_planner_filters_hallucinated_poi():
    """有 poi_id 但不在候选 → 编造景点，丢弃。"""
    fake = FakeProvider(json_responses={"行程规划JSON": {
        "days": [{"day": 1, "title": "x", "weather_note": "晴",
                  "items": [{"time": "09:00", "name": "编造的景点", "poi_id": "nope-999", "note": ""}]}],
        "summary": "x", "warnings": [],
    }})
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert out["itinerary"]["days"][0]["items"] == []


def test_planner_keeps_example_food_without_poi_id():
    """无 poi_id 的条目（LLM 生成的示例餐饮/住宿）保留。"""
    fake = FakeProvider(json_responses={"行程规划JSON": {
        "days": [{"day": 1, "title": "x", "weather_note": "晴",
                  "items": [{"time": "12:30", "name": "点都德（示例）", "note": "午餐"}]}],
        "summary": "x", "warnings": [],
    }})
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert len(out["itinerary"]["days"][0]["items"]) == 1


def test_planner_days_null_tolerated():
    fake = FakeProvider(json_responses={"行程规划JSON": {"days": None, "summary": "无行程。", "warnings": []}})
    out = planner.planner_node(_state(), fake)  # type: ignore[arg-type]
    assert out["phase"] == "answered"
    assert "行程总结" in out["last_reply"]


def test_format_itinerary_shape():
    text = planner.format_itinerary(ITINERARY)
    assert "第 1 天" in text and "广州塔" in text and "## " in text
```

`test_graph.py` 重写（5 节点事件序 + 全流程；fake 检索注入复用 test_researcher 的 fake）：

```python
from app import events
from app.graph import build_graph

from conftest import FakeProvider
from test_researcher import _kwargs as _researcher_kwargs  # fake weather/search/normalize
from test_planner import CANDIDATES  # 复用候选常量


def _fake() -> FakeProvider:
    return FakeProvider(json_responses={
        "已有画像": {
            "destination": "广州", "duration_days": 3, "start_date": None,
            "budget_cny": 8000, "travelers": 2, "preferences": ["美食"], "missing": [],
        },
        "推荐要点JSON": {"recommendations": [{"poi_id": "guangzhou-001", "reason": "夜景绝佳"}]},
        "预算分配JSON": {"items": [{"category": "住宿", "amount": 3200, "note": "中档酒店"}],
                        "total": 8000},
        "行程规划JSON": {"days": [{"day": 1, "title": "广州地标", "weather_note": "晴",
                                  "items": [{"time": "19:00", "name": "广州塔", "poi_id": "guangzhou-001", "note": ""}]}],
                        "summary": "OK", "warnings": []},
        "汇总JSON": {"summary": "整体节奏合理。", "tips": ["周三起降温"]},
    })


def test_full_planning_flow():
    graph = build_graph(_fake(), **_researcher_kwargs())  # type: ignore[arg-type]
    result = graph.invoke({
        "messages": [{"role": "user", "content": "10月去广州玩3天，预算8000，喜欢美食"}],
        "phase": "",
    })
    assert result["phase"] == "answered"
    assert result["itinerary"]["days"][0]["items"][0]["poi_id"] == "guangzhou-001"
    assert result["budget_plan"]["checked"] is True
    assert result["supervisor_summary"]["summary"] == "整体节奏合理。"
    assert result["last_reply"].startswith("## ")
    assert "## 预算分配" in result["last_reply"]


def test_incomplete_request_ends_at_analyst():
    fake = FakeProvider(json_responses={"最新需求": {
        "destination": None, "duration_days": 3, "start_date": None,
        "budget_cny": None, "travelers": 1, "preferences": [],
        "missing": ["destination"],
    }})
    graph = build_graph(fake, **_researcher_kwargs())  # type: ignore[arg-type]
    result = graph.invoke({
        "messages": [{"role": "user", "content": "帮我规划3天"}],
        "phase": "",
    })
    assert result["phase"] == "asking"
    assert "想去哪个城市" in result["messages"][-1]["content"]


def test_unknown_region_ends_with_hint_without_supervisor():
    """未知目的地 → researcher 置 region_resolved=False → planner 输出降级回复后直接 END，
    supervisor 不运行（防止空行程覆盖降级回复），不调用 LLM。"""
    fake = FakeProvider(json_responses={"已有画像": {
        "destination": "巴黎", "duration_days": 3, "start_date": None,
        "budget_cny": 8000, "travelers": 2, "preferences": [], "missing": [],
    }})
    graph = build_graph(fake, **_researcher_kwargs())  # type: ignore[arg-type]
    result = graph.invoke({
        "messages": [{"role": "user", "content": "10月去巴黎玩3天，预算8000"}],
        "phase": "",
    })
    assert result["phase"] == "answered"
    assert "暂不支持" in result["last_reply"] and "巴黎" in result["last_reply"]
    # budget 在并行 fan-out 中与 researcher 同时执行（不依赖 candidates），照常调用 LLM 一次；
    # researcher 早退、planner 走降级分支、supervisor 不运行 → 共 analyst + budget 2 次
    assert len(fake.calls) == 2


def test_nodes_publish_agent_status():
    q = events.subscribe()
    try:
        graph = build_graph(_fake(), **_researcher_kwargs())  # type: ignore[arg-type]
        graph.invoke({
            "messages": [{"role": "user", "content": "10月去广州玩3天，预算8000，喜欢美食"}],
            "phase": "",
        })
        seen = []
        while not q.empty():
            ev = q.get_nowait()
            if ev["type"] == "agent_status":
                seen.append((ev["data"]["agent"], ev["data"]["status"]))
    finally:
        events.unsubscribe(q)
    by_agent: dict[str, list[str]] = {}
    for agent, status in seen:
        by_agent.setdefault(agent, []).append(status)
    for agent in ("analyst", "researcher", "budget", "planner", "supervisor"):
        assert by_agent.get(agent) == ["start", "done"], f"{agent}: {by_agent.get(agent)}"
```

`test_chat.py`：`_kwargs` 改从 test_researcher 导入（`build_graph(fake, **_researcher_kwargs())`）；FakeProvider json_responses 加 `"推荐要点JSON"`/`"预算分配JSON"`/`"行程规划JSON"`/`"汇总JSON"` 四组 key（结构沿用 test_graph 的 `_fake()`，见上；ITINERARY 保留）。`test_chat_continues_session` 的第二次请求（"第二天换成博物馆"）在 M3 会再次走全图（无 checkpointer，M4 才有增量）——断言 `len(msgs) == 4` 保持成立（两轮各 user+assistant）。

- [ ] **Step 1: 重写测试**（上文三文件逐字使用；先跑失败）
- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_planner.py tests/test_graph.py tests/test_chat.py -v`
Expected: FAIL（planner_node 旧签名、graph 旧拓扑等）

- [ ] **Step 3: Write the implementation**（planner.py / analyst.py 提示词 / graph.py / chat.py / AgentProcessPanel.tsx 按上文改动）

- [ ] **Step 4: Run full suite + frontend type check**

Run: `.venv/Scripts/python -m pytest tests/ -v` → 全绿
Run（frontend/ 下）: `npx tsc --noEmit` → 0 errors

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/planner.py backend/app/agents/analyst.py backend/app/graph.py backend/app/api/chat.py backend/tests/test_planner.py backend/tests/test_graph.py backend/tests/test_chat.py frontend/src/components/AgentProcessPanel.tsx
git commit -m "feat: 5-node parallel graph (analyst → ‖researcher‖budget‖ → planner → supervisor)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: README 更新 + 旧语料删除重建 + 真实冒烟（controller 手动执行）

**Files:**
- Modify: `README.md`（34 省文案、M3 里程碑行 ✅、演示说明）

**代码部分（implementer）**：

- [ ] **Step 1: README 更新**
  - 第 4 行"支持国内约 20 个旅游城市" → "支持全国 34 个省级行政区的著名景点检索"
  - 第 16 行 RAG 知识库行 → "**Chroma + BGE（bge-small-zh-v1.5，ModelScope 下载）**，全国 34 省级行政区著名景点（省份-城市-景点三级粒度检索）"
  - 里程碑表 M3 行：`| M3 完整协作（Supervisor 路由 + Researcher/Budget + 并行） | ⬜ |` → `✅ 完成`（内容列改为 `M3 完整协作（34 省景点库 + Supervisor 路由 + Researcher/Budget + 并行）`）
  - 快速开始第 2 步注释 "生成 20 城 POI 语料（DeepSeek 约 20 次调用）" → "生成 34 省 POI 语料（DeepSeek 约 34 次调用）"
  - 演示段落补充：搜"广东"→全省景点、"佛山"（库外城市）→广东省其他景点

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README — 34-province KB, M3 milestone done

Co-Authored-By: Claude <noreply@anthropic.com>"
```

**冒烟清单（controller 在本任务完成后、最终审查前手动执行；DEEPSEEK_API_KEY 只经环境变量传递，绝不落盘/打印）**：

1. 删除旧数据：`rm backend/data/poi_corpus.jsonl` + `rm -rf backend/data/chroma`（spec §4 删除替换）
2. 真实语料生成：`cd backend && .venv/Scripts/python -m app.rag.generate`（34 次 DeepSeek 调用，产出新 34 省语料）
3. 真实入库：`.venv/Scripts/python -m app.rag.ingest`
4. 静态断言：`python -c` 解析 `poi_corpus.jsonl` → `set(province) == 34 省全集`、每省 ≥ 3 条
5. 三级检索冒烟：`python -c` 调 `app.rag.retriever.search_pois("广东"/"广州"/"佛山")` → 广东 4 类命中、广州细化、佛山 fallback 到广东
6. 双终端 demo：uvicorn :8000 + vite :5173 → "10月去成都玩3天，预算8000，喜欢美食" → 面板 **10 条 agent_status**（5 agent × start/done）、回复含行程 + 预算表 + 总体建议；再试"帮我规划佛山的行程"→ 广东景点 fallback
7. 结果记入 `.superpowers/sdd/progress.md`

---

## 执行顺序与分支

- 分支：`feat/m3-full-collaboration`（从当前 main 创建）
- 任务顺序：1 → 2 → 3 → 4 → 5 → 6 → 7 → 8；每任务 implementer → task reviewer → ledger；全部完成后最终 whole-branch review（opus）→ 修复波 → push → PR #3
- 模型建议：Task 1/4/5/6 为机械实现（计划含完整代码）→ 最便宜档；Task 2/3/7 为多文件重构/集成 → 标准档；最终 whole-branch review → 最贵档
