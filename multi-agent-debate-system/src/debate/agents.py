"""The courtroom nodes, built around an injected `LLMClient`.

`build_nodes(client, settings, log)` returns the node callables LangGraph wires
together: opening statements, cross-examination turns, the Judge's per-round
direction, and the final advisory opinion. Injecting the client (rather than
importing Ollama here) is what lets the tests run the entire proceeding against a
`FakeLLM` with no model loaded.

Each node degrades instead of crashing: a failed counsel call becomes a labelled
placeholder entry so the proceeding still reaches an opinion, and a failed opinion
call becomes a labelled `[INCOMPLETE]` verdict. The graph therefore always
terminates with a `final_verdict`.
"""

from __future__ import annotations

from .config import Settings
from .llm import DebateLLMError, LLMClient
from .prompts import (
    DEFENCE_SYSTEM,
    JUDGE_DIRECT_SYSTEM,
    JUDGE_VERDICT_SYSTEM,
    PROSECUTION_SYSTEM,
    build_closing_user,
    build_direct_user,
    build_examination_user,
    build_opening_user,
    build_verdict_user,
)
from .schemas import (
    CourtRecordEntry,
    DebateState,
    ExaminationTurn,
    Statement,
    Verdict,
)

_SYSTEM = {"defence": DEFENCE_SYSTEM, "prosecution": PROSECUTION_SYSTEM}
_LABEL = {"defence": "DEFENCE", "prosecution": "PROSECUTION"}


def _degraded_entry(phase: str, round_: int, role: str, reason: str) -> CourtRecordEntry:
    return CourtRecordEntry(
        phase=phase, round=round_, role=role,
        text=f"[{role} counsel could not speak: {reason}]",
    )


def _degraded_verdict(reason: str) -> Verdict:
    return Verdict(
        recommendation=f"[INCOMPLETE - the court could not deliver an opinion: {reason}]",
        confidence=0.0,
        grounds=["opinion synthesis failed"],
        why_alternative_is_weaker=["not assessed"],
        conditions=["re-run the proceeding; the model call did not return a valid opinion"],
        dissenting_considerations=["none available"],
    )


def build_nodes(client: LLMClient, settings: Settings, log=None):
    log = log or (lambda *a, **k: None)

    def _model_for(role: str) -> str:
        return settings.defence_model if role == "defence" else settings.prosecution_model

    # --- opening / closing statements --------------------------------------------

    def _statement(state: DebateState, role: str, phase: str) -> dict:
        model = _model_for(role)
        log(_LABEL[role], f"({model}) {phase} statement...")
        builder = build_opening_user if phase == "opening" else build_closing_user
        try:
            payload = client.generate_json(
                model, _SYSTEM[role], builder(state, role), Statement,
                think=settings.advocate_think,
                num_predict=settings.advocate_num_predict,
                timeout=settings.advocate_timeout,
            )
            entry = CourtRecordEntry(
                phase=phase, round=0, role=role,
                text=payload.statement, key_points=payload.key_points,
            )
        except DebateLLMError as exc:
            log(_LABEL[role], f"FAILED: {exc}")
            entry = _degraded_entry(phase, 0, role, str(exc))
        log(_LABEL[role], entry.text)
        return {"record": [entry]}

    def defence_opening(state: DebateState) -> dict:
        log("PHASE", "=== OPENING STATEMENTS ===")
        return _statement(state, "defence", "opening")

    def prosecution_opening(state: DebateState) -> dict:
        return _statement(state, "prosecution", "opening")

    def defence_closing(state: DebateState) -> dict:
        log("PHASE", "=== CLOSING STATEMENTS ===")
        return _statement(state, "defence", "closing")

    def prosecution_closing(state: DebateState) -> dict:
        return _statement(state, "prosecution", "closing")

    # --- cross-examination turns -------------------------------------------------

    def _examine(state: DebateState, role: str) -> dict:
        r = state["round"]
        model = _model_for(role)
        if role == "defence":
            log("ROUND", f"--- cross-examination round {r} of {state['max_rounds']} ---")
        log(_LABEL[role], f"({model}) cross-examining...")
        try:
            payload = client.generate_json(
                model, _SYSTEM[role], build_examination_user(state, role), ExaminationTurn,
                think=settings.advocate_think,
                num_predict=settings.advocate_num_predict,
                timeout=settings.advocate_timeout,
            )
            entry = CourtRecordEntry(
                phase="examination", round=r, role=role,
                text=payload.response, question=payload.question_to_opponent,
                rebuttals_to=payload.rebuttals_to,
            )
        except DebateLLMError as exc:
            log(_LABEL[role], f"FAILED: {exc}")
            entry = _degraded_entry("examination", r, role, str(exc))
        log(_LABEL[role], entry.text)
        if entry.question:
            log(_LABEL[role] + "/Q", entry.question)
        return {"record": [entry]}

    def defence_examine(state: DebateState) -> dict:
        return _examine(state, "defence")

    def prosecution_examine(state: DebateState) -> dict:
        return _examine(state, "prosecution")

    # --- judge ------------------------------------------------------------------

    def judge_direct(state: DebateState) -> dict:
        # Observe what was just heard, direct the next round, then advance the
        # examination counter; route_examination (graph.py) reads it to loop/close.
        next_round = state["round"] + 1
        log("JUDGE", f"({settings.judge_model}) directing (entering round {next_round})...")
        try:
            direction = client.generate_text(
                settings.judge_model, JUDGE_DIRECT_SYSTEM, build_direct_user(state),
                think=settings.enable_thinking,
                num_predict=settings.judge_direct_num_predict,
                timeout=settings.judge_timeout,
            )
        except DebateLLMError as exc:
            direction = f"[bench direction unavailable: {exc}]"
        log("JUDGE/direct", direction)
        return {"judge_directions": [direction], "round": next_round}

    def verdict(state: DebateState) -> dict:
        log("JUDGE", f"({settings.judge_model}) delivering the advisory opinion...")
        try:
            v = client.generate_json(
                settings.judge_model, JUDGE_VERDICT_SYSTEM, build_verdict_user(state), Verdict,
                think=settings.enable_thinking,
                num_predict=settings.judge_verdict_num_predict,
                timeout=settings.judge_timeout,
            )
        except DebateLLMError as exc:
            log("JUDGE", f"opinion FAILED: {exc}")
            v = _degraded_verdict(str(exc))
        return {"final_verdict": v}

    return {
        "defence_opening": defence_opening,
        "prosecution_opening": prosecution_opening,
        "defence_examine": defence_examine,
        "prosecution_examine": prosecution_examine,
        "judge_direct": judge_direct,
        "defence_closing": defence_closing,
        "prosecution_closing": prosecution_closing,
        "verdict": verdict,
    }
