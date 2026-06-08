"""Data shapes for the courtroom proceeding.

The decision is put "on trial". **Defence counsel** argues for the proposition,
**Prosecution counsel** argues against it, and the **Judge** presides — directing
the examination and finally delivering an *advisory opinion* (a strong
recommendation, not a binding winner-takes-all verdict).

Two layers:

* **Wire schemas** the LLM must fill in (`DebateFraming`, `Statement`,
  `ExaminationTurn`, `Verdict`). These are handed to Ollama as
  `format=<json-schema>` so output is grammar-constrained, then validated with
  Pydantic. This is where structured-output reliability lives.
* **State** (`DebateState`) — the LangGraph working memory threaded through every
  node. The `record` field uses a reducer so each node returns only its new entry
  and the graph accumulates the full court transcript.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Optional, TypedDict

from pydantic import BaseModel, Field

ROLE_LABEL = {"defence": "DEFENCE counsel", "prosecution": "PROSECUTION counsel"}


class DebateFraming(BaseModel):
    """The two opposing positions, derived from the question before the proceeding.

    Pinning each side of the bar to an explicit, mutually-exclusive stance is the
    fix for the convergence trap: when a question is an "A or B" choice it has no
    single "proposition", so two helpful models told to argue "for"/"against" both
    drift to the conventionally-correct answer. Explicit assigned positions keep the
    proceeding genuinely adversarial.
    """

    defence_position: str = Field(
        description="One concrete, committed sentence stating the position the "
        "DEFENCE defends (e.g. 'The startup SHOULD build auth in-house')."
    )
    prosecution_position: str = Field(
        description="One concrete, committed sentence stating the directly OPPOSITE "
        "position the PROSECUTION argues (e.g. 'The startup should NOT build auth "
        "in-house and should use a managed provider')."
    )


class Statement(BaseModel):
    """An opening or closing statement from one counsel."""

    statement: str = Field(
        description="The full statement, as a complete self-contained paragraph of "
        "at least 4 sentences. Write the actual argument in full — NOT a title, NOT "
        "a lead-in, and never ending on a colon."
    )
    key_points: list[str] = Field(
        default_factory=list,
        description="The pillars of the case this statement rests on, strongest first.",
    )


class ExaminationTurn(BaseModel):
    """One cross-examination turn: answer the opponent, then put a question to them.

    `round` is deliberately NOT here: the orchestrator knows the round, so asking
    the model for it only invites error. We stamp it in code.
    """

    response: str = Field(
        description="Answer the opposing counsel's last question/challenge head-on "
        "and advance your case, as a complete paragraph of at least 4 sentences. "
        "Never concede your position."
    )
    question_to_opponent: str = Field(
        description="ONE pointed question or hypothetical situation you put to the "
        "opposing counsel that exposes a specific weakness in their position."
    )
    rebuttals_to: list[str] = Field(
        default_factory=list,
        description="Specific points from the opponent you are directly rebutting.",
    )


class CourtRecordEntry(BaseModel):
    """One entry in the court transcript, stamped with where it belongs."""

    phase: str  # "opening" | "examination" | "closing"
    round: int  # 0 for opening/closing; 1..N for examination rounds
    role: str  # "defence" | "prosecution"
    text: str  # statement text or examination response
    question: Optional[str] = None  # the question put to the opponent (examination)
    rebuttals_to: list[str] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    """The Judge's advisory opinion. NOT a winner declaration and NOT 'it depends'.

    A strong recommendation the reader can act on — *and the reader is the final
    decision-maker*. The schema forces the courtroom shape: 'I suggest A on these
    grounds (XYZ); the alternative B is likely weaker for these reasons (LMN); here
    is when B is actually the better call instead.'
    """

    recommendation: str = Field(
        description="The advisory recommendation, phrased as counsel to the reader: "
        "'I suggest <course> because ...'. Strong and concrete, but NOT absolute — "
        "never tell the reader they are wrong or foolish to choose otherwise."
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="0..1 confidence in the recommendation."
    )
    grounds: list[str] = Field(
        description="The specific grounds — evidence and arguments from the "
        "proceeding — on which the suggested course is favoured (the 'XYZ')."
    )
    why_alternative_is_weaker: list[str] = Field(
        description="Where and why the alternative course is likely inferior (the "
        "'LMN'). Measured and specific, never dismissive."
    )
    conditions: list[str] = Field(
        description="The circumstances under which the alternative actually becomes "
        "the better choice instead. This turns a binary call into an engineering "
        "decision."
    )
    dissenting_considerations: list[str] = Field(
        description="The strongest points in favour of the alternative that the "
        "reader should still weigh before deciding. Never empty in a real case."
    )


class RubricScore(BaseModel):
    """Machine-assisted scoring of a finished proceeding against `eval/criteria.md`.

    The brief's rubric is meant to be scored *manually*; this is a model-assisted
    first pass over a 25-question battery, to be spot-checked by a human. Each axis
    is 1-5; the pass bar (criteria 1, 2, 5 all >= 4) is computed in code, not by the
    model, so it cannot be gamed by an over-generous grader.
    """

    role_commitment: int = Field(ge=1, le=5, description="Did both counsel hold their assigned side across every phase, with no defection or 'both sides have a point'?")
    direct_engagement: int = Field(ge=1, le=5, description="Did each side answer the opponent's pointed questions and rebut their strongest specific points, not ignore them?")
    internal_consistency: int = Field(ge=1, le=5, description="Is each side coherent across rounds — no self-contradiction or abandoned claims?")
    active_judge: int = Field(ge=1, le=5, description="Did the bench's directions steer toward genuinely unaddressed dimensions, and did the proceeding shift in response?")
    decision_usefulness: int = Field(ge=1, le=5, description="Is the advisory opinion genuinely useful — advisory not absolute, specific grounds, precise conditions, real (non-boilerplate) dissent?")
    notes: str = Field(default="", description="2-4 sentences justifying the scores, citing specifics from the proceeding.")


class DebateState(TypedDict):
    """LangGraph state. Threaded through every node; `record` accumulates entries."""

    question: str
    defence_position: str  # what the Defence defends (set at framing)
    prosecution_position: str  # what the Prosecution argues
    round: int  # current examination round, 1-based (0 before examination opens)
    max_rounds: int  # number of cross-examination rounds
    history_mode: str  # hybrid | full | last
    record: Annotated[list[CourtRecordEntry], add]  # the full court transcript
    judge_directions: Annotated[list[str], add]  # the bench's per-round directions
    final_verdict: Optional[Verdict]
