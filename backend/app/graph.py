from langgraph.graph import END, StateGraph

from app.state import TravelState


def stub_node(state: TravelState) -> dict:
    """M1 占位节点：仅标记图可运行，后续里程碑替换为真实 Agent 节点。"""
    return {"phase": "ready"}


def build_graph():
    g = StateGraph(TravelState)
    g.add_node("stub", stub_node)
    g.set_entry_point("stub")
    g.add_edge("stub", END)
    return g.compile()


graph = build_graph()
