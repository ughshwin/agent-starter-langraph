"""CLI entrypoint for the Agentic Pipeline Inspector.

    python main.py inspect <repo_path> [--format json|md] [--model M] [--out F] [--verbose]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from inspector.config import Settings              # noqa: E402
from inspector.graph import build_graph            # noqa: E402
from inspector.llm import LLMClient, OllamaLLM     # noqa: E402
from inspector.observability import RunLogger      # noqa: E402
from inspector.report import render_json, render_markdown  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="inspector", description="Production-readiness auditor")
    sub = p.add_subparsers(dest="command", required=True)
    insp = sub.add_parser("inspect", help="inspect a repository")
    insp.add_argument("repo_path")
    insp.add_argument("--format", choices=["json", "md"], default="md")
    insp.add_argument("--model", default=None)
    insp.add_argument("--out", default=None)
    insp.add_argument("--verbose", action="store_true")
    return p


def run_inspection(repo_path: str, fmt: str, settings: Settings,
                   client: LLMClient, log: RunLogger | None = None) -> str:
    graph = build_graph(client, settings, log=log)
    initial = {"repo_path": repo_path, "repo_language": "", "depth_plan": {},
               "findings": [], "tools_run": [], "not_assessed": [], "report": None}
    final = graph.invoke(initial)
    report = final["report"]
    return render_json(report) if fmt == "json" else render_markdown(report)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not Path(args.repo_path).is_dir():
        print(f"error: not a directory: {args.repo_path}", file=sys.stderr)
        return 2
    settings = Settings(model=args.model or Settings.model, verbose=args.verbose)
    settings.validate()
    log = RunLogger(Path("inspector_run.jsonl"), verbose=args.verbose)
    client = OllamaLLM(settings.model, timeout=settings.llm_timeout,
                       num_predict=settings.llm_num_predict,
                       retries=settings.validation_retries,
                       log=lambda *a: log.note(" ".join(map(str, a))))
    output = run_inspection(args.repo_path, args.format, settings, client, log)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"report written to {args.out}", file=sys.stderr)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
