"""The four debate nodes, built around an injected `LLMClient`.

`build_nodes(client, settings, log)` returns the node callables LangGraph wires
together. Injecting the client (rather than importing Ollama here) is what lets
the tests run the entire graph against a `FakeLLM` with no model loaded.

Each node degrades instead of crashing: a failed advocate call becomes a labelled
placeholder argument so the debate still reaches a verdict, and a failed verdict
call becomes a labelled `[INCOMPLETE]` verdict. The graph therefore always
terminates with a `final_verdict` — the multi-agent analog of the research agent's
"never hang, always return a labelled best-effort answer".
"""

from __future__ import annotations

from .llm import DebateLLMError, LLMClient
from .prompts import (
    JUDGE_OBSERVE_SYSTEM,
    JUDGE_VERDICT_SYSTEM,
    OPPOSER_SYSTEM,
    PROPOSER_SYSTEM,
    build_advocate_user,
    build_observe_user,
    build_verdict_user,
)
from .schemas import ArgumentPayload, DebateState, RoundArgument, Verdict
from .config import Settings


def _degraded_argument(round_: int, side: str, reason: str) -> RoundArgument:
    return RoundArgument(
        round=round_,
        argument=f"[{side} could not generate an argument this round: {reason}]",
        rebuttals_to=[],
    )


def _degraded_verdict(reason: str) -> Verdict:
    return Verdict(
        recommendation=f"[INCOMPLETE - the Judge could not synthesise a verdict: {reason}]",
        confidence=0.0,
        key_factors=["verdict synthesis failed"],
        conditions=["re-run the debate; the model call did not return a valid verdict"],
        dissenting_considerations=["none available"],
    )


def build_nodes(client: LLMClient, settings: Settings, log=None):
    log = log or (lambda *a, **k: None)

    def _advocate(state: DebateState, side: str, model: str, system: str) -> dict:
        r = state["round"]
        if side == "proposer":
            log("ROUND", f"--- round {r} of {state['max_rounds']} ---")
        log(side.upper(), f"({model}) arguing...")
        user = build_advocate_user(state, side)
        try:
            payload = client.generate_json(
                model, system, user, ArgumentPayload,
                think=False,
                num_predict=settings.advocate_num_predict,
                timeout=settings.advocate_timeout,
            )
            arg = RoundArgument(
                round=r, argument=payload.argument, rebuttals_to=payload.rebuttals_to
            )
        except DebateLLMError as exc:
            log(side.upper(), f"FAILED: {exc}")
            arg = _degraded_argument(r, side, str(exc))
        log(side.upper(), arg.argument)
        key = "proposer_arguments" if side == "proposer" else "opposer_arguments"
        return {key: [arg]}

    def proposer(state: DebateState) -> dict:
        return _advocate(state, "proposer", settings.proposer_model, PROPOSER_SYSTEM)

    def opposer(state: DebateState) -> dict:
        return _advocate(state, "opposer", settings.opposer_model, OPPOSER_SYSTEM)

    def judge_observe(state: DebateState) -> dict:
        log("JUDGE", f"({settings.judge_model}) observing round {state['round']}...")
        user = build_observe_user(state)
        try:
            obs = client.generate_text(
                settings.judge_model, JUDGE_OBSERVE_SYSTEM, user,
                think=settings.enable_thinking,
                num_predict=settings.judge_observe_num_predict,
                timeout=settings.judge_timeout,
            )
        except DebateLLMError as exc:
            obs = f"[Judge observation unavailable: {exc}]"
        log("JUDGE/steer", obs)
        # Advance the round here; route_round (graph.py) reads it to loop or finish.
        return {"judge_observations": [obs], "round": state["round"] + 1}

    def judge_verdict(state: DebateState) -> dict:
        log("JUDGE", f"({settings.judge_model}) synthesising verdict...")
        user = build_verdict_user(state)
        try:
            verdict = client.generate_json(
                settings.judge_model, JUDGE_VERDICT_SYSTEM, user, Verdict,
                think=settings.enable_thinking,
                num_predict=settings.judge_verdict_num_predict,
                timeout=settings.judge_timeout,
            )
        except DebateLLMError as exc:
            log("JUDGE", f"verdict FAILED: {exc}")
            verdict = _degraded_verdict(str(exc))
        return {"final_verdict": verdict}

    return {
        "proposer": proposer,
        "opposer": opposer,
        "judge_observe": judge_observe,
        "judge_verdict": judge_verdict,
    }
