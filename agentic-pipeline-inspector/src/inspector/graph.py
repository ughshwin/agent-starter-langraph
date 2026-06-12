"""LangGraph wiring: triage → five dimension nodes (sequential) → synthesise → END.

Sequential per spec Decision 1; the reducer-backed state means switching to
parallel dimension fan-out later needs no schema change."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .config import Settings
from .llm import LLMClient
from .nodes import make_dimension_nodes, make_synthesise_node
from .observability import RunLogger
from .schemas import InspectionState
from .triage import make_triage_node


def build_graph(client: LLMClient, settings: Settings, log: RunLogger | None = None):
    g = StateGraph(InspectionState)
    g.add_node("triage", make_triage_node(client, settings, log))
    dims = make_dimension_nodes(settings, log)
    for name, fn in dims.items():
        g.add_node(name, fn)
    g.add_node("synthesise", make_synthesise_node(client, log))

    order = ["security", "code_quality", "container", "dependencies", "operational"]
    g.add_edge(START, "triage")
    g.add_edge("triage", order[0])
    for a, b in zip(order, order[1:]):
        g.add_edge(a, b)
    g.add_edge(order[-1], "synthesise")
    g.add_edge("synthesise", END)
    return g.compile()
