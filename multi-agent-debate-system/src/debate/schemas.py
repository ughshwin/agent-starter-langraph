"""Data shapes for the debate.

Two layers:

* **Wire schemas** the LLM must fill in (`ArgumentPayload`, `Verdict`). These are
  handed to Ollama as `format=<json-schema>` so the model's output is grammar-
  constrained, then validated with Pydantic. This is where structured-output
  reliability lives.
* **State** (`DebateState`) — the LangGraph working memory threaded through every
  node. List fields use reducers so each node returns only its new item and the
  graph accumulates.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Optional, TypedDict

from pydantic import BaseModel, Field


class ArgumentPayload(BaseModel):
    """What a Proposer/Opposer must emit each round.

    `round` is deliberately NOT here: the orchestrator knows the round number, so
    asking the model for it only invites it to get it wrong. We wrap this payload
    into a `RoundArgument` in code.
    """

    argument: str = Field(
        description="The strongest case for your assigned side this round, as a "
        "complete, self-contained paragraph of at least 4 full sentences. Write the "
        "actual reasoning in full — NOT a title, NOT a lead-in, and never ending "
        "with a colon or a phrase like 'here's why'."
    )
    rebuttals_to: list[str] = Field(
        default_factory=list,
        description="Specific points from the opponent you are directly rebutting. "
        "Empty only in round 1 when there is nothing to rebut yet.",
    )


class RoundArgument(BaseModel):
    """An `ArgumentPayload` stamped with the round it belongs to (stored in state)."""

    round: int
    argument: str
    rebuttals_to: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    """The Judge's final synthesis. The schema is the point: it forces nuance.

    `conditions` is the most important field — it converts a binary
    recommendation into an engineering decision ("X holds if ...").
    """

    recommendation: str = Field(
        description="The concrete recommendation. Take a position; do not say 'it depends'."
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="0..1 confidence in the recommendation."
    )
    key_factors: list[str] = Field(
        description="The factors that actually drove the decision, strongest first."
    )
    conditions: list[str] = Field(
        description="Conditions under which the recommendation holds, and when the "
        "opposite choice becomes correct instead."
    )
    dissenting_considerations: list[str] = Field(
        description="The strongest points from the losing side that a reader should "
        "still weigh. Never empty in a real debate."
    )


class DebateState(TypedDict):
    """LangGraph state. Threaded through every node; reducers accumulate lists."""

    question: str
    round: int  # current round, 1-based
    max_rounds: int
    history_mode: str  # hybrid | full | last
    proposer_arguments: Annotated[list[RoundArgument], add]
    opposer_arguments: Annotated[list[RoundArgument], add]
    judge_observations: Annotated[list[str], add]
    final_verdict: Optional[Verdict]
