"""Evaluation harness: run the debate over the question battery, save traces.

    python eval/run_eval.py                 # all questions, default models
    python eval/run_eval.py --only 1        # just the Auth0 question
    python eval/run_eval.py --rounds 2 --history full

Each question gets a fresh debate (no shared state). Full trace + verdict are
written to eval_runs/. Score the outputs by hand against criteria.md.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

from debate.config import Settings  # noqa: E402
from debate.runner import format_verdict, preflight, run_debate  # noqa: E402
from questions import QUESTIONS  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only", type=int, default=None, help="Run only question N (1-based).")
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--history", default="hybrid", choices=("hybrid", "full", "last"))
    p.add_argument("--single-model", default=None)
    p.add_argument("--no-think", action="store_true",
                   help="Disable Judge thinking mode (use for non-thinking models).")
    args = p.parse_args()

    settings = Settings(
        max_rounds=args.rounds,
        history_mode=args.history,
        enable_thinking=not args.no_think,
    )
    if args.single_model:
        settings = settings.with_single_model(args.single_model)

    ok, message = preflight(settings)
    if not ok:
        print(f"Preflight failed:\n{message}", file=sys.stderr)
        return 2

    questions = QUESTIONS if args.only is None else [QUESTIONS[args.only - 1]]
    base = 1 if args.only is None else args.only

    out_dir = os.path.join(_HERE, "..", "eval_runs")
    os.makedirs(out_dir, exist_ok=True)

    results = []
    for offset, q in enumerate(questions):
        n = base + offset
        print("\n" + "#" * 70)
        print(f"# QUESTION {n}: {q}")
        print("#" * 70)
        start = time.time()
        state = run_debate(q, settings)
        elapsed = time.time() - start
        verdict = state.get("final_verdict")
        verdict_text = format_verdict(verdict) if verdict else "(no verdict)"
        print(f"\n>>> Q{n} VERDICT ({elapsed:.0f}s):\n{verdict_text}")

        path = os.path.join(out_dir, f"q{n}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Q{n}: {q}\n\nModels: {settings.models()}\n")
            f.write(f"Rounds: {settings.max_rounds} | History: {settings.history_mode}\n\n")
            f.write("## Transcript\n\n")
            for r in range(1, settings.max_rounds + 1):
                f.write(f"### Round {r}\n")
                for a in state["proposer_arguments"]:
                    if a.round == r:
                        f.write(f"**Proposer:** {a.argument}\n\n")
                        if a.rebuttals_to:
                            f.write(f"_Rebuts:_ {'; '.join(a.rebuttals_to)}\n\n")
                for a in state["opposer_arguments"]:
                    if a.round == r:
                        f.write(f"**Opposer:** {a.argument}\n\n")
                        if a.rebuttals_to:
                            f.write(f"_Rebuts:_ {'; '.join(a.rebuttals_to)}\n\n")
            f.write("## Judge observations\n\n")
            for i, o in enumerate(state["judge_observations"], 1):
                f.write(f"{i}. {o}\n\n")
            f.write(f"## Verdict\n\n```\n{verdict_text}\n```\n")
        results.append((n, elapsed, path))

    print("\n" + "=" * 70)
    print("SUMMARY")
    for n, elapsed, path in results:
        print(f"Q{n:<2} {elapsed:>4.0f}s  -> {os.path.relpath(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
