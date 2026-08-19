from app.graph import graph


def test_empty_graph_runs():
    result = graph.invoke({"messages": [], "phase": ""})
    assert result["phase"] == "ready"
