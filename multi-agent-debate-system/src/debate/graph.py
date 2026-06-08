"""LangGraph wiring.

```
START → proposer → opposer → judge_observe → [route_round]
                                                ├─ round ≤ max → proposer  (loop)
                                                └─ else        → judge_verdict → END
```

`route_round` is the entire termination policy in one place. The round counter is
incremented inside `judge_observe`, so by the time we route it already reflects the
round we are *about* to run. min 2 / max 3 rounds is enforced by `Settings`.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .agents import build_nodes
from .config import Settings
from .llm import LLMClient
from .schemas import DebateState


def route_round(state: DebateState) -> str:
    """Loop back for another round, or proceed to the final verdict."""
    return "proposer" if state["round"] <= state["max_rounds"] else "judge_verdict"


def build_graph(client: LLMClient, settings: Settings, log=None):
    nodes = build_nodes(client, settings, log=log)
    g = StateGraph(DebateState)
    g.add_node("proposer", nodes["proposer"])
    g.add_node("opposer", nodes["opposer"])
    g.add_node("judge_observe", nodes["judge_observe"])
    g.add_node("judge_verdict", nodes["judge_verdict"])

    g.add_edge(START, "proposer")
    g.add_edge("proposer", "opposer")
    g.add_edge("opposer", "judge_observe")
    g.add_conditional_edges(
        "judge_observe",
        route_round,
        {"proposer": "proposer", "judge_verdict": "judge_verdict"},
    )
    g.add_edge("judge_verdict", END)
    return g.compile()
