from app.agents import analyst

from conftest import FakeProvider


def _state(messages: list[dict]) -> dict:
    return {"messages": messages, "phase": ""}


def _fake() -> FakeProvider:
    return FakeProvider(
        json_responses={
            "成都": {
                "destination": "成都", "duration_days": 3,
                "start_date": None, "budget_cny": 8000,
                "travelers": 2, "preferences": ["美食"],
                "missing": [],
            }
        }
    )


def test_analyst_complete_request_routes_to_planning():
    fake = _fake()
    out = analyst.analyst_node(_state([{"role": "user", "content": "10月去成都玩3天，预算8000，喜欢美食"}]),
                               fake)  # type: ignore[arg-type]
    assert out["phase"] == "planning"
    assert out["profile"]["destination"] == "成都"
    assert out["profile"]["duration_days"] == 3
    assert out["profile"]["budget_cny"] == 8000
    assert out["profile"]["preferences"] == ["美食"]
    assert "messages" not in out  # 无需追问，不追加对话


def test_analyst_missing_destination_asks_question():
    # FakeProvider 按 prompt 子串匹配：key 必须命中 analyst 组装后的 user 内容
    # （"已有画像：…\n最新需求：帮我规划3天行程\n…" → 用 "规划"）
    fake = FakeProvider(
        json_responses={
            "规划": {
                "destination": None, "duration_days": 3, "start_date": None,
                "budget_cny": None, "travelers": 1, "preferences": [],
                "missing": ["destination"],
            }
        }
    )
    out = analyst.analyst_node(_state([{"role": "user", "content": "帮我规划3天行程"}]),
                               fake)  # type: ignore[arg-type]
    assert out["phase"] == "asking"
    question = out["messages"][-1]["content"]
    assert out["messages"][-1]["role"] == "assistant"
    assert "想去哪个城市" in question


def test_analyst_missing_duration_asks_question():
    fake = FakeProvider(
        json_responses={
            "上海": {
                "destination": "上海", "duration_days": None, "start_date": None,
                "budget_cny": None, "travelers": 1, "preferences": [],
                "missing": ["duration_days"],
            }
        }
    )
    out = analyst.analyst_node(_state([{"role": "user", "content": "想去上海玩"}]),
                               fake)  # type: ignore[arg-type]
    assert out["phase"] == "asking"
    assert "几天" in out["messages"][-1]["content"]


def test_analyst_second_turn_merges_profile():
    fake = _fake()
    prior_profile = {"destination": "成都", "duration_days": 3, "budget_cny": 5000}
    state = _state([{"role": "user", "content": "10月去成都玩3天预算8000"}])
    state["profile"] = prior_profile
    out = analyst.analyst_node(state, fake)  # type: ignore[arg-type]
    assert out["profile"]["destination"] == "成都"
    assert out["profile"]["budget_cny"] == 8000  # 新信息覆盖旧值
    assert out["profile"]["travelers"] == 2


def test_analyst_coerces_numeric_strings_to_int():
    """LLM 输出数值字符串（"8000"/"3"）时 budget_cny/duration_days 转 int（M3 防御）。"""
    fake = FakeProvider(
        json_responses={
            "成都": {
                "destination": "成都", "duration_days": "3",
                "start_date": None, "budget_cny": "8000",
                "travelers": 2, "preferences": ["美食"],
                "missing": [],
            }
        }
    )
    out = analyst.analyst_node(_state([{"role": "user", "content": "10月去成都玩3天，预算8000"}]),
                               fake)  # type: ignore[arg-type]
    assert out["profile"]["duration_days"] == 3
    assert out["profile"]["budget_cny"] == 8000


def test_analyst_keeps_non_numeric_budget_as_is():
    """非数值（如 "三天"）不做强制转换，原样保留。"""
    fake = FakeProvider(
        json_responses={
            "成都": {
                "destination": "成都", "duration_days": "三天",
                "start_date": None, "budget_cny": None,
                "travelers": 1, "preferences": [],
                "missing": [],
            }
        }
    )
    out = analyst.analyst_node(_state([{"role": "user", "content": "10月去成都玩3天"}]),
                               fake)  # type: ignore[arg-type]
    assert out["profile"]["duration_days"] == "三天"
    assert "budget_cny" not in out["profile"]  # None（未知）不写入画像
