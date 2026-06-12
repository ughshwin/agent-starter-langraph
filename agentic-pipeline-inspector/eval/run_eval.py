"""Run the inspector against a list of repo paths and write a report per repo.

Usage: python eval/run_eval.py <repo_path> [<repo_path> ...]

This drives the REAL agent (real scanners + Ollama). It is an integration runner,
not a unit test — it needs the tools from setup.sh installed and Ollama running."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from inspector.config import Settings           # noqa: E402
from inspector.llm import OllamaLLM             # noqa: E402
from inspector.observability import RunLogger   # noqa: E402
from main import run_inspection                 # noqa: E402


def main(paths: list[str]) -> int:
    settings = Settings(verbose=True)
    settings.validate()
    out_dir = Path(__file__).parent
    for p in paths:
        if not Path(p).is_dir():
            print(f"[eval] skip (not a dir): {p}", file=sys.stderr)
            continue
        name = Path(p).name
        log = RunLogger(out_dir / f"run_{name}.jsonl", verbose=True)
        client = OllamaLLM(settings.model, timeout=settings.llm_timeout,
                           num_predict=settings.llm_num_predict,
                           retries=settings.validation_retries)
        md = run_inspection(p, "md", settings, client, log)
        (out_dir / f"out_{name}.md").write_text(md, encoding="utf-8")
        print(f"[eval] wrote out_{name}.md")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python eval/run_eval.py <repo_path> [...]", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1:]))
