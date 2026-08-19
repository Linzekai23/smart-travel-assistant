from functools import partial

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.analyst import analyst_node
from app.agents.planner import planner_node
from app.llm.deepseek import DeepSeekProvider
from app.state import TravelState
from app.rag.retriever import get_poi as _default_get_poi
from app.rag.retriever import normalize_city as _default_normalize_city
from app.rag.retriever import search_nearby as _default_search_nearby
from app.rag.retriever import search_pois as _default_search_pois
from app.tools.weather_api import get_weather as _default_weather


def build_graph(
    llm_provider: DeepSeekProvider,
    *,
    weather_fn=_default_weather,
    search_pois_fn=_default_search_pois,
    search_nearby_fn=_default_search_nearby,
    get_poi_fn=_default_get_poi,
    normalize_city_fn=_default_normalize_city,
) -> CompiledStateGraph:
    """装配双节点图：analyst →（需求齐全时）→ planner → END；
    需求缺失时 analyst 追问后直接 END（等待用户下一轮消息）。

    weather_fn / search_pois_fn 等为 Planner 的依赖注入点
    （测试传 fake 实现，生产用默认真实实现）。"""
    g = StateGraph(TravelState)
    g.add_node("analyst", partial(analyst_node, llm=llm_provider))
    g.add_node(
        "planner",
        partial(
            planner_node,
            llm=llm_provider,
            weather_fn=weather_fn,
            search_pois_fn=search_pois_fn,
            search_nearby_fn=search_nearby_fn,
            get_poi_fn=get_poi_fn,
            normalize_city_fn=normalize_city_fn,
        ),
    )
    g.set_entry_point("analyst")
    g.add_edge("planner", END)
    g.add_conditional_edges(
        "analyst",
        lambda state: "planner" if state.get("phase") == "planning" else END,
        {"planner": "planner", END: END},
    )
    return g.compile()
