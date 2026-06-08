"""LangGraph wiring for the courtroom proceeding.

```
START → defence_opening → prosecution_opening → judge_direct ─┐
                                                              │ (route_examination)
                  ┌─ round ≤ max ── defence_examine ──────────┘
                  │                       │
                  │                 prosecution_examine
                  │                       │
                  └───────────────── judge_direct  (loop)
                  else → defence_closing → prosecution_closing → verdict → END
```

`judge_direct` is the hub: it directs the next round, increments the examination
counter, and `route_examination` reads that counter to loop or move to closing.
The counter starts at 0; the first `judge_direct` (after openings) advances it to
1, so the proceeding runs exactly `max_rounds` cross-examination rounds.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .agents import build_nodes
from .config import Settings
from .llm import LLMClient
from .schemas import DebateState


def route_examination(state: DebateState) -> str:
    """After the bench directs: open another examination round, or move to closing."""
    return "defence_examine" if state["round"] <= state["max_rounds"] else "defence_closing"


def build_graph(client: LLMClient, settings: Settings, log=None):
    nodes = build_nodes(client, settings, log=log)
    g = StateGraph(DebateState)
    for name, fn in nodes.items():
        g.add_node(name, fn)

    g.add_edge(START, "defence_opening")
    g.add_edge("defence_opening", "prosecution_opening")
    g.add_edge("prosecution_opening", "judge_direct")
    g.add_conditional_edges(
        "judge_direct",
        route_examination,
        {"defence_examine": "defence_examine", "defence_closing": "defence_closing"},
    )
    g.add_edge("defence_examine", "prosecution_examine")
    g.add_edge("prosecution_examine", "judge_direct")
    g.add_edge("defence_closing", "prosecution_closing")
    g.add_edge("prosecution_closing", "verdict")
    g.add_edge("verdict", END)
    return g.compile()
