"""CLI entry point for the multi-agent debate system.

    python main.py "Should a startup with 50k DAU build auth in-house or use Auth0?"
    python main.py --rounds 2 --history full "..."
    python main.py --single-model qwen3:8b "..."        # one model for all roles
    python main.py --json "..."                          # machine-readable verdict

Options let you A/B the brief's decisions: --history {hybrid,full,last} and the
per-role --proposer-model / --opposer-model / --judge-model.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace

# Force UTF-8 stdout: thinking models emit non-ASCII that crashes the cp1252
# Windows console otherwise (lesson from the research agent).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from debate.config import (  # noqa: E402
    DEFAULT_JUDGE_MODEL,
    DEFAULT_OPPOSER_MODEL,
    DEFAULT_PROPOSER_MODEL,
    Settings,
)
from debate.runner import preflight, print_summary, run_debate  # noqa: E402


def build_settings(args) -> Settings:
    settings = Settings(
        proposer_model=args.proposer_model,
        opposer_model=args.opposer_model,
        judge_model=args.judge_model,
        max_rounds=args.rounds,
        history_mode=args.history,
        enable_thinking=not args.no_think,
        verbose=not args.quiet,
    )
    if args.single_model:
        settings = settings.with_single_model(args.single_model)
    return settings


def main() -> int:
    p = argparse.ArgumentParser(description="Multi-agent adversarial debate system.")
    p.add_argument("question", nargs="*", help="The technical decision to debate.")
    p.add_argument("--proposer-model", default=DEFAULT_PROPOSER_MODEL)
    p.add_argument("--opposer-model", default=DEFAULT_OPPOSER_MODEL)
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    p.add_argument("--single-model", default=None,
                   help="Use one model for all three roles (overrides per-role).")
    p.add_argument("--rounds", type=int, default=3, help="Debate rounds (2 or 3).")
    p.add_argument("--history", default="hybrid", choices=("hybrid", "full", "last"))
    p.add_argument("--no-think", action="store_true",
                   help="Disable Judge thinking mode (use for non-thinking models).")
    p.add_argument("--quiet", action="store_true", help="Hide the live debate trace.")
    p.add_argument("--json", action="store_true",
                   help="Print only the final verdict as JSON.")
    args = p.parse_args()

    question = " ".join(args.question).strip() or input("Decision question: ").strip()
    if not question:
        print("No question provided.", file=sys.stderr)
        return 1

    try:
        settings = build_settings(args)
        settings.validate()
    except ValueError as exc:
        print(f"Bad settings: {exc}", file=sys.stderr)
        return 1

    if args.json:
        settings = replace(settings, verbose=False)

    ok, message = preflight(settings)
    if not ok:
        print(f"Preflight failed:\n{message}", file=sys.stderr)
        return 2

    state = run_debate(question, settings)
    verdict = state.get("final_verdict")

    if args.json:
        print(verdict.model_dump_json(indent=2) if verdict else "null")
    else:
        print_summary(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
