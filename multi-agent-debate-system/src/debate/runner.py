"""High-level orchestration: preflight, run the debate, format the result.

`run_debate` builds the LangGraph with a real `OllamaLLM` (or an injected client
for tests), threads the initial state through it, and returns the final state with
the `Verdict`. The live trace (ROUND / PROPOSER / OPPOSER / JUDGE) prints as it
goes — as with the research agent, the reasoning trace is as important as the
answer for understanding what happened.
"""

from __future__ import annotations

import sys

import ollama

from .config import Settings
from .graph import build_graph
from .llm import LLMClient, OllamaLLM
from .schemas import DebateState, Verdict


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


def initial_state(question: str, settings: Settings) -> DebateState:
    return {
        "question": question,
        "round": 1,
        "max_rounds": settings.max_rounds,
        "history_mode": settings.history_mode,
        "proposer_arguments": [],
        "opposer_arguments": [],
        "judge_observations": [],
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
    graph = build_graph(client, settings, log=log)
    # recursion_limit comfortably exceeds 3 rounds * 3 nodes + verdict.
    return graph.invoke(initial_state(question, settings), {"recursion_limit": 50})


def format_verdict(v: Verdict) -> str:
    def bullets(items):
        return "\n".join(f"  - {x}" for x in items) if items else "  (none)"

    return (
        f"RECOMMENDATION: {v.recommendation}\n"
        f"CONFIDENCE: {v.confidence:.2f}\n\n"
        f"KEY FACTORS:\n{bullets(v.key_factors)}\n\n"
        f"CONDITIONS (when each choice is correct):\n{bullets(v.conditions)}\n\n"
        f"DISSENTING CONSIDERATIONS:\n{bullets(v.dissenting_considerations)}"
    )


def print_summary(state: DebateState) -> None:
    print("\n" + "=" * 70)
    print(f"QUESTION: {state['question']}")
    print(f"ROUNDS: {state['max_rounds']}  |  HISTORY MODE: {state['history_mode']}")
    print("=" * 70)
    verdict = state.get("final_verdict")
    if verdict is None:
        print("No verdict was produced.", file=sys.stderr)
        return
    print(format_verdict(verdict))
