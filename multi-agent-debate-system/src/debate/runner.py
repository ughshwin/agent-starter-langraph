"""High-level orchestration: preflight, run the debate, format the result.

`run_debate` builds the LangGraph with a real `OllamaLLM` (or an injected client
for tests), threads the initial state through it, and returns the final state with
the advisory `Verdict`. The live trace (PHASE / ROUND / DEFENCE / PROSECUTION /
JUDGE) prints as it goes — the reasoning trace is as important as the opinion for
understanding what happened.
"""

from __future__ import annotations

import sys

import ollama

from .config import Settings
from .graph import build_graph
from .llm import LLMClient, OllamaLLM
from .prompts import (
    FRAMING_SYSTEM,
    SCORING_SYSTEM,
    build_framing_user,
    build_scoring_user,
)
from .schemas import DebateFraming, DebateState, RubricScore, Verdict


def make_logger(verbose: bool):
    def log(label: str, text: str) -> None:
        if verbose:
            print(f"\n[{label}] {text}", flush=True)
    return log


def preflight(settings: Settings) -> tuple[bool, str]:
    """Check Ollama is up and every role model is pulled. Returns (ok, message)."""
    try:
        installed = {m.model for m in ollama.Client().list().models}
    except Exception as exc:
        return False, (
            f"Cannot reach Ollama ({type(exc).__name__}: {exc}). "
            "Is the Ollama server running?"
        )
    wanted = set(settings.models().values())
    missing = sorted(m for m in wanted if m not in installed)
    if missing:
        hint = "\n".join(f"  ollama pull {m}" for m in missing)
        return False, f"Missing model(s):\n{hint}"
    return True, "ok"


def _fallback_framing(question: str) -> DebateFraming:
    return DebateFraming(
        defence_position=f"Defend the proposition in the question: {question}",
        prosecution_position=f"Argue against the proposition in the question: {question}",
    )


def frame_debate(
    question: str, settings: Settings, client: LLMClient, log=None
) -> DebateFraming:
    """Derive the two explicit opposing positions before the proceeding opens.

    Degrades to generic defend/oppose stances if the framing call fails, so a flaky
    framing step never blocks the proceeding."""
    log = log or (lambda *a, **k: None)
    try:
        framing = client.generate_json(
            settings.judge_model, FRAMING_SYSTEM, build_framing_user(question),
            DebateFraming, think=False, num_predict=800,
            timeout=settings.judge_timeout,
        )
    except Exception:  # noqa: BLE001 — framing is best-effort, never block the proceeding
        framing = _fallback_framing(question)
    log("FRAMING", f"DEFENCE defends: {framing.defence_position}")
    log("FRAMING", f"PROSECUTION argues: {framing.prosecution_position}")
    return framing


def initial_state(
    question: str, settings: Settings, framing: DebateFraming | None = None
) -> DebateState:
    if framing is None:
        framing = _fallback_framing(question)
    return {
        "question": question,
        "defence_position": framing.defence_position,
        "prosecution_position": framing.prosecution_position,
        "round": 0,  # advanced to 1 by the first judge_direct, after openings
        "max_rounds": settings.max_rounds,
        "history_mode": settings.history_mode,
        "record": [],
        "judge_directions": [],
        "final_verdict": None,
    }


def run_debate(
    question: str, settings: Settings, client: LLMClient | None = None
) -> DebateState:
    """Run the full debate and return the final state (includes `final_verdict`)."""
    settings.validate()
    log = make_logger(settings.verbose)
    if client is None:
        client = OllamaLLM(validation_retries=settings.validation_retries, log=log)
    framing = frame_debate(question, settings, client, log=log)
    graph = build_graph(client, settings, log=log)
    # Nodes per run: openings (2) + judge_direct (max+1) + examination (2*max) +
    # closing (2) + verdict (1). Scale the limit with max_rounds (+buffer) so high
    # round counts don't trip LangGraph's recursion guard.
    recursion_limit = settings.max_rounds * 4 + 20
    return graph.invoke(
        initial_state(question, settings, framing),
        {"recursion_limit": recursion_limit},
    )


def score_proceeding(
    state: DebateState, verdict_text: str, settings: Settings, client: LLMClient,
    log=None,
) -> RubricScore | None:
    """Machine-assisted rubric scoring of a finished proceeding (eval only).

    Returns None if the scorer call fails — scoring must never crash the battery."""
    log = log or (lambda *a, **k: None)
    try:
        return client.generate_json(
            settings.judge_model, SCORING_SYSTEM,
            build_scoring_user(state, verdict_text), RubricScore,
            think=settings.enable_thinking,
            num_predict=settings.judge_verdict_num_predict,
            timeout=settings.judge_timeout,
        )
    except Exception as exc:  # noqa: BLE001 — scoring is best-effort
        log("SCORER", f"scoring failed: {exc}")
        return None


def format_verdict(v: Verdict) -> str:
    def bullets(items):
        return "\n".join(f"  - {x}" for x in items) if items else "  (none)"

    return (
        "THE COURT'S OPINION  (advisory — the final decision is yours)\n\n"
        f"RECOMMENDATION: {v.recommendation}\n"
        f"CONFIDENCE: {v.confidence:.2f}\n\n"
        f"GROUNDS (why this is suggested):\n{bullets(v.grounds)}\n\n"
        f"WHY THE ALTERNATIVE IS LIKELY WEAKER:\n{bullets(v.why_alternative_is_weaker)}\n\n"
        f"WHEN THE ALTERNATIVE IS THE BETTER CHOICE:\n{bullets(v.conditions)}\n\n"
        f"CONSIDERATIONS TO STILL WEIGH:\n{bullets(v.dissenting_considerations)}\n\n"
        "— This is a strong recommendation, not a binding ruling. Weigh it and decide."
    )


def print_summary(state: DebateState) -> None:
    print("\n" + "=" * 70)
    print(f"DECISION ON TRIAL: {state['question']}")
    print(
        f"CROSS-EXAMINATION ROUNDS: {state['max_rounds']}  |  "
        f"HISTORY MODE: {state['history_mode']}"
    )
    print("=" * 70)
    verdict = state.get("final_verdict")
    if verdict is None:
        print("No opinion was produced.", file=sys.stderr)
        return
    print(format_verdict(verdict))
