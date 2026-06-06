"""CLI entry point for the research agent.

Usage:
    python main.py "your question here"
    python main.py            # then type the question when prompted

Options:
    --model       Ollama model to use (default: llama3.1)
    --max-iters   Max tool-calling iterations before giving up (default: 10)
    --quiet       Hide the reasoning trace; print only the final answer
"""

import argparse
import os
import sys

# The model can emit non-ASCII (e.g. the symbol pi). The default Windows console
# is cp1252 and would crash on those, so force UTF-8 with replacement.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from agent import ReActAgent


def main() -> int:
    parser = argparse.ArgumentParser(description="CLI ReAct research agent.")
    parser.add_argument("question", nargs="*", help="The question to answer.")
    parser.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", "llama3.1"))
    parser.add_argument("--max-iters", type=int, default=10)
    parser.add_argument("--quiet", action="store_true",
                        help="Hide the reasoning trace.")
    args = parser.parse_args()

    question = " ".join(args.question).strip()
    if not question:
        question = input("Question: ").strip()
    if not question:
        print("No question provided.", file=sys.stderr)
        return 1

    agent = ReActAgent(
        model=args.model,
        max_iterations=args.max_iters,
        verbose=not args.quiet,
    )

    try:
        answer = agent.run(question)
    except Exception as exc:
        # Most failures here are the LLM call: Ollama not running, or the model
        # not pulled. Surface a useful hint rather than a raw traceback.
        print(f"\nLLM error: {exc}\n"
              f"Is Ollama running and is the model pulled? "
              f"Try: `ollama pull {args.model}`", file=sys.stderr)
        return 2

    print("\n" + "=" * 60)
    print("ANSWER:")
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
