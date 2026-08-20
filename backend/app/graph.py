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
    checkpointer=None,
) -> CompiledStateGraph:
    """装配 5 节点图：analyst → ‖researcher‖budget‖ → planner → supervisor → END。

    需求缺失时 analyst 追问后直接 END（等待用户下一轮消息）。
    weather_fn / search_pois_fn / normalize_region_fn 为 Researcher 的依赖注入点
    （测试传 fake 实现，生产用默认真实实现）。
    checkpointer：langgraph checkpointer（如 SqliteSaver/MemorySaver），
    传入后同 thread_id 的多次 invoke 自动恢复/延续 state（M4 对话能力）。"""
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
    # planner 未知区域（region_resolved=False）或候选为空（KB 空/未入库）时
    # 直接输出降级回复，不走 supervisor——否则 supervisor 会用空行程覆盖降级回复
    g.add_conditional_edges(
        "planner",
        lambda state: END if state.get("region_resolved") is False or not state.get("candidates") else "supervisor",
        {"supervisor": "supervisor", END: END},
    )
    g.add_edge("supervisor", END)
    return g.compile(checkpointer=checkpointer)
