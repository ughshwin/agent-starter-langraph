"""Evaluation harness: run the courtroom proceeding over the question battery and
document every proceeding verbatim.

    python eval/run_eval.py                 # all questions, default models
    python eval/run_eval.py --only 7        # just question 7
    python eval/run_eval.py --start 11      # resume from question 11 (keep earlier files)
    python eval/run_eval.py --rounds 4      # shallower/faster battery
    python eval/run_eval.py --no-score      # skip machine-assisted rubric scoring

For each question it writes, under eval_runs/:
  * qNN.md                  — the COMPLETE verbatim proceeding (every statement, every
                              cross-examination turn + question, every bench direction,
                              the advisory opinion, and the machine-assisted rubric).
  * FULL_PROCEEDINGS.md     — all proceedings concatenated into one document.
  * RUBRIC.md               — the filled rubric: a score table + per-question notes.

Nothing is paraphrased — the markdown contains the models' exact text.
"""

from __future__ import annotations

import argparse
import json
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
from debate.llm import OllamaLLM  # noqa: E402
from debate.runner import (  # noqa: E402
    format_verdict,
    initial_state,
    preflight,
    score_proceeding,
)
from debate.graph import build_graph  # noqa: E402
from debate.runner import frame_debate  # noqa: E402
from questions import QUESTIONS  # noqa: E402

OUT_DIR = os.path.join(_HERE, "..", "eval_runs")


# --- verbatim rendering -----------------------------------------------------

def _entries(record, phase, role=None, rnd=None):
    out = [e for e in record if e.phase == phase]
    if role is not None:
        out = [e for e in out if e.role == role]
    if rnd is not None:
        out = [e for e in out if e.round == rnd]
    return out


def _render_statement(record, phase, role):
    es = _entries(record, phase, role=role)
    if not es:
        return f"_(no {role} {phase} statement recorded)_\n\n"
    e = es[0]
    md = e.text.strip() + "\n\n"
    if e.key_points:
        md += "_Key points:_\n" + "".join(f"- {k}\n" for k in e.key_points) + "\n"
    return md


def _render_examination_turn(record, rnd, role):
    es = _entries(record, "examination", role=role, rnd=rnd)
    if not es:
        return f"_(no {role} turn recorded in round {rnd})_\n\n"
    e = es[0]
    md = e.text.strip() + "\n\n"
    if e.question:
        md += f"**Question put to the opponent:** {e.question.strip()}\n\n"
    if e.rebuttals_to:
        md += "_Rebuts:_ " + "; ".join(e.rebuttals_to) + "\n\n"
    return md


def render_proceeding_md(n, question, state, settings, elapsed, score) -> str:
    record = state["record"]
    directions = state["judge_directions"]
    max_rounds = settings.max_rounds

    md = [f"## Q{n}: {question}\n"]
    md.append(
        f"- **Models** — Defence: `{settings.defence_model}` · "
        f"Prosecution: `{settings.prosecution_model}` · Judge: `{settings.judge_model}`\n"
        f"- **Cross-examination rounds:** {max_rounds} · **History mode:** "
        f"{settings.history_mode} · **Elapsed:** {elapsed:.0f}s\n"
        f"- **Defence position:** {state['defence_position']}\n"
        f"- **Prosecution position:** {state['prosecution_position']}\n"
    )

    md.append("### Opening statements\n")
    md.append("**DEFENCE — opening statement**\n\n" + _render_statement(record, "opening", "defence"))
    md.append("**PROSECUTION — opening statement**\n\n" + _render_statement(record, "opening", "prosecution"))

    md.append("### Cross-examination\n")
    for r in range(1, max_rounds + 1):
        md.append(f"#### Round {r}\n")
        # The bench direction the counsel acted on entering this round is directions[r-1].
        if r - 1 < len(directions):
            md.append("**THE BENCH directs:** " + directions[r - 1].strip() + "\n\n")
        md.append("**DEFENCE cross-examines**\n\n" + _render_examination_turn(record, r, "defence"))
        md.append("**PROSECUTION cross-examines**\n\n" + _render_examination_turn(record, r, "prosecution"))

    # The final bench utterance (after the last round) informs the opinion, not a round.
    if len(directions) > max_rounds:
        md.append("**THE BENCH — closing reflection before the opinion:** "
                  + directions[max_rounds].strip() + "\n\n")

    md.append("### Closing statements\n")
    md.append("**DEFENCE — closing statement**\n\n" + _render_statement(record, "closing", "defence"))
    md.append("**PROSECUTION — closing statement**\n\n" + _render_statement(record, "closing", "prosecution"))

    md.append("### The Court's advisory opinion\n")
    verdict = state.get("final_verdict")
    md.append("```\n" + (format_verdict(verdict) if verdict else "(no opinion)") + "\n```\n")

    md.append("### Rubric (machine-assisted)\n")
    md.append(_render_score_block(score))
    return "\n".join(md) + "\n---\n"


# --- rubric -----------------------------------------------------------------

def _passed(s) -> bool:
    # Pass bar (criteria.md): role commitment, engagement, usefulness all >= 4.
    return s is not None and s.role_commitment >= 4 and s.direct_engagement >= 4 \
        and s.decision_usefulness >= 4


def _render_score_block(s) -> str:
    if s is None:
        return "_(scoring unavailable)_\n"
    return (
        f"| Role commit | Engagement | Consistency | Active Judge | Useful | Pass? |\n"
        f"|---|---|---|---|---|---|\n"
        f"| {s.role_commitment} | {s.direct_engagement} | {s.internal_consistency} "
        f"| {s.active_judge} | {s.decision_usefulness} | "
        f"{'✅' if _passed(s) else '❌'} |\n\n"
        f"_Evaluator notes:_ {s.notes}\n"
    )


# --- main -------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only", type=int, default=None, help="Run only question N (1-based).")
    p.add_argument("--start", type=int, default=1, help="Resume from question N (keeps earlier qNN.md).")
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--history", default="hybrid", choices=("hybrid", "full", "last"))
    p.add_argument("--single-model", default=None)
    p.add_argument("--no-think", action="store_true")
    p.add_argument("--no-score", action="store_true", help="Skip machine-assisted rubric scoring.")
    args = p.parse_args()

    settings = Settings(
        max_rounds=args.rounds,
        history_mode=args.history,
        enable_thinking=not args.no_think,
        verbose=True,
    )
    if args.single_model:
        settings = settings.with_single_model(args.single_model)

    ok, message = preflight(settings)
    if not ok:
        print(f"Preflight failed:\n{message}", file=sys.stderr)
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    client = OllamaLLM(validation_retries=settings.validation_retries)

    if args.only is not None:
        indices = [args.only]
    else:
        indices = list(range(args.start, len(QUESTIONS) + 1))

    results = []  # (n, question, elapsed, score)
    for n in indices:
        q = QUESTIONS[n - 1]
        print("\n" + "#" * 78)
        print(f"# QUESTION {n}/{len(QUESTIONS)}: {q[:70]}...")
        print("#" * 78, flush=True)

        start = time.time()
        # Run the proceeding (frame → graph) directly so we keep the client for scoring.
        framing = frame_debate(q, settings, client)
        graph = build_graph(client, settings)
        state = graph.invoke(
            initial_state(q, settings, framing),
            {"recursion_limit": settings.max_rounds * 4 + 20},
        )
        elapsed = time.time() - start

        verdict = state.get("final_verdict")
        verdict_text = format_verdict(verdict) if verdict else "(no opinion)"
        print(f"\n>>> Q{n} OPINION ({elapsed:.0f}s):\n{verdict_text}", flush=True)

        score = None
        if not args.no_score:
            print(f"\n>>> scoring Q{n}...", flush=True)
            score = score_proceeding(state, verdict_text, settings, client)

        page = render_proceeding_md(n, q, state, settings, elapsed, score)
        with open(os.path.join(OUT_DIR, f"q{n:02d}.md"), "w", encoding="utf-8") as f:
            f.write(f"# Q{n}\n\n" + page)
        _persist_score(n, q, score)
        results.append((n, q, elapsed, score))

    # Assemble the combined documents from every per-question page on disk, so a
    # resumed/partial run still produces complete master files.
    _assemble_master(settings)

    print("\n" + "=" * 78)
    print("SUMMARY")
    for n, q, elapsed, score in results:
        verdict_pass = "✅" if _passed(score) else ("❌" if score else "–")
        print(f"Q{n:<2} {elapsed:>4.0f}s  pass={verdict_pass}")
    print(f"\nWrote: {os.path.relpath(os.path.join(OUT_DIR, 'FULL_PROCEEDINGS.md'))} and RUBRIC.md")
    return 0


_SCORES_FILE = os.path.join(OUT_DIR, "scores.jsonl")


def _persist_score(n, question, score) -> None:
    """Append this question's score so RUBRIC.md survives resumes (last write wins)."""
    rows = _load_scores()
    rows[n] = {
        "n": n, "question": question,
        "score": (score.model_dump() if score is not None else None),
    }
    with open(_SCORES_FILE, "w", encoding="utf-8") as f:
        for k in sorted(rows):
            f.write(json.dumps(rows[k]) + "\n")


def _load_scores() -> dict:
    rows = {}
    if os.path.exists(_SCORES_FILE):
        with open(_SCORES_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    rows[r["n"]] = r
    return rows


def _assemble_master(settings: Settings) -> None:
    """Concatenate all qNN.md into FULL_PROCEEDINGS.md, and (re)build RUBRIC.md."""
    pages = sorted(f for f in os.listdir(OUT_DIR) if f.startswith("q") and f[1:3].isdigit())
    full = ["# Multi-Agent Courtroom — Full Proceedings\n",
            f"Defence `{settings.defence_model}` vs Prosecution `{settings.prosecution_model}`, "
            f"Judge `{settings.judge_model}`. {settings.max_rounds} cross-examination rounds, "
            f"history `{settings.history_mode}`. Every proceeding below is the models' verbatim "
            f"output — opening statements, cross-examination, closing statements, advisory opinion.\n"]
    for pf in pages:
        with open(os.path.join(OUT_DIR, pf), encoding="utf-8") as fh:
            body = fh.read()
        # Strip the per-file "# Qn" h1 so the master keeps one heading level.
        body = "\n".join(l for l in body.splitlines() if not l.startswith("# Q"))
        full.append(body)
    with open(os.path.join(OUT_DIR, "FULL_PROCEEDINGS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(full))

    # RUBRIC.md — the filled scorecard, built from the persisted scores.
    rows = _load_scores()
    md = ["# Proceeding Rubric — machine-assisted scores\n",
          "Scored 1–5 per axis against `eval/criteria.md` by an independent evaluator "
          "pass (the Judge model, not a participant). Pass bar: role commitment, "
          "engagement, and usefulness all ≥ 4. **Machine-assisted — spot-check by hand.**\n",
          "| Q | Question | Role | Engage | Consist | Judge | Useful | Pass |",
          "|---|----------|------|--------|---------|-------|--------|------|"]
    passes = 0
    scored = 0
    for n in sorted(rows):
        r = rows[n]
        s = r.get("score")
        if s is None:
            md.append(f"| {n} | {_short(r['question'])} | – | – | – | – | – | – |")
            continue
        scored += 1
        ok = s["role_commitment"] >= 4 and s["direct_engagement"] >= 4 and s["decision_usefulness"] >= 4
        passes += int(ok)
        md.append(
            f"| {n} | {_short(r['question'])} | {s['role_commitment']} | "
            f"{s['direct_engagement']} | {s['internal_consistency']} | "
            f"{s['active_judge']} | {s['decision_usefulness']} | {'✅' if ok else '❌'} |"
        )
    md.append(f"\n**Pass rate:** {passes}/{scored} scored proceedings.\n")
    md.append("## Evaluator notes per question\n")
    for n in sorted(rows):
        s = rows[n].get("score")
        if s:
            md.append(f"**Q{n}.** {s['notes']}\n")
    with open(os.path.join(OUT_DIR, "RUBRIC.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))


def _short(q: str) -> str:
    return (q[:60] + "…") if len(q) > 61 else q


if __name__ == "__main__":
    raise SystemExit(main())
