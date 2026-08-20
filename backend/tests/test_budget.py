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
