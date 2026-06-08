"""Neutral re-scoring of the proceedings with a model from a FOURTH lab.

The in-run rubric (RUBRIC.md) is scored by the Judge model (qwen3:32b) — the same
model that writes the opinions, so its marks are likely generous. This re-scores
every proceeding with an independent reasoning model that was neither an advocate
nor the judge (default: Mistral's `magistral:24b`), to remove the self-grading
bias. It reads the verbatim qNN.md (minus the existing rubric, to avoid anchoring)
and asks the neutral model to score the five rubric axes.

    python eval/rescore.py                       # score all qNN.md
    python eval/rescore.py --scorer phi4-reasoning:14b

Writes eval_runs/RUBRIC_NEUTRAL.md, scores_neutral.jsonl, and a delta vs RUBRIC.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, "..", "src"))
OUT_DIR = os.path.join(_HERE, "..", "eval_runs")

from debate.llm import OllamaLLM  # noqa: E402
from debate.prompts import SCORING_SYSTEM  # noqa: E402
from debate.schemas import RubricScore  # noqa: E402

_AXES = ["role_commitment", "direct_engagement", "internal_consistency",
         "active_judge", "decision_usefulness"]


def _proceeding_text(md: str) -> str:
    """The full proceeding minus the prior machine rubric (avoid anchoring)."""
    cut = md.find("### Rubric")
    return (md[:cut] if cut != -1 else md).strip()


def _passed(s: dict) -> bool:
    return s["role_commitment"] >= 4 and s["direct_engagement"] >= 4 \
        and s["decision_usefulness"] >= 4


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scorer", default="magistral:24b",
                   help="Neutral scorer model (a lab used for neither advocate nor judge).")
    p.add_argument("--only", type=int, default=None)
    args = p.parse_args()

    client = OllamaLLM(validation_retries=2)
    pages = sorted(f for f in os.listdir(OUT_DIR) if re.fullmatch(r"q\d\d\.md", f))
    if args.only is not None:
        pages = [f"q{args.only:02d}.md"]

    out_rows = {}
    for pf in pages:
        n = int(pf[1:3])
        with open(os.path.join(OUT_DIR, pf), encoding="utf-8") as fh:
            body = _proceeding_text(fh.read())
        user = (
            "Score the following finished courtroom proceeding against the five "
            "rubric axes. Be critical and specific; do not inflate.\n\n"
            f"{body}\n\n"
            "Return ONE JSON object (no markdown, no prose) with keys: "
            "role_commitment, direct_engagement, internal_consistency, active_judge, "
            "decision_usefulness (each an integer 1-5), and notes (a string of 2-4 "
            "sentences citing specifics)."
        )
        print(f"scoring Q{n} with {args.scorer}...", flush=True)
        try:
            s = client.generate_json(
                args.scorer, SCORING_SYSTEM, user, RubricScore,
                think=True, num_predict=6000, timeout=900,
            ).model_dump()
        except Exception as exc:  # noqa: BLE001
            print(f"  Q{n} scoring failed: {exc}", file=sys.stderr)
            s = None
        out_rows[n] = s
        # Persist incrementally so a long run is resumable/inspectable.
        with open(os.path.join(OUT_DIR, "scores_neutral.jsonl"), "w", encoding="utf-8") as f:
            for k in sorted(out_rows):
                f.write(json.dumps({"n": k, "scorer": args.scorer, "score": out_rows[k]}) + "\n")

    _write_report(args.scorer, out_rows)
    return 0


def _write_report(scorer: str, rows: dict) -> None:
    # Load the judge-model rubric for a side-by-side delta.
    judge = {}
    jf = os.path.join(OUT_DIR, "scores.jsonl")
    if os.path.exists(jf):
        with open(jf, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    judge[r["n"]] = r.get("score")

    md = [f"# Neutral Rubric — scored by `{scorer}` (4th lab, not an advocate or the judge)\n",
          "Independent re-score to remove the self-grading bias in `RUBRIC.md` "
          "(which was scored by the judge model). Same axes, same pass bar "
          "(role commitment, engagement, usefulness all ≥ 4).\n",
          "| Q | Role | Engage | Consist | Judge | Useful | Pass | (judge-model Useful) |",
          "|---|------|--------|---------|-------|--------|------|----------------------|"]
    passes = scored = 0
    sums = {a: 0 for a in _AXES}
    jsums = {a: 0 for a in _AXES}
    paired = 0
    for n in sorted(rows):
        s = rows[n]
        if s is None:
            md.append(f"| {n} | – | – | – | – | – | – | – |")
            continue
        scored += 1
        passes += int(_passed(s))
        for a in _AXES:
            sums[a] += s[a]
        j = judge.get(n)
        ju = j["decision_usefulness"] if j else "–"
        if j:
            paired += 1
            for a in _AXES:
                jsums[a] += j[a]
        md.append(
            f"| {n} | {s['role_commitment']} | {s['direct_engagement']} | "
            f"{s['internal_consistency']} | {s['active_judge']} | "
            f"{s['decision_usefulness']} | {'✅' if _passed(s) else '❌'} | {ju} |"
        )
    md.append(f"\n**Neutral pass rate:** {passes}/{scored}.\n")
    if scored:
        md.append("### Average score per axis — neutral vs judge-model\n")
        md.append("| Axis | Neutral avg | Judge-model avg |")
        md.append("|------|-------------|-----------------|")
        for a in _AXES:
            navg = sums[a] / scored
            javg = (jsums[a] / paired) if paired else 0
            md.append(f"| {a} | {navg:.2f} | {javg:.2f} |")
    md.append("\n## Neutral evaluator notes per question\n")
    for n in sorted(rows):
        if rows[n]:
            md.append(f"**Q{n}.** {rows[n]['notes']}\n")
    with open(os.path.join(OUT_DIR, "RUBRIC_NEUTRAL.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"\nWrote {os.path.relpath(os.path.join(OUT_DIR, 'RUBRIC_NEUTRAL.md'))}")


if __name__ == "__main__":
    raise SystemExit(main())
