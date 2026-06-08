"""Build eval_runs/INDEX.md — a one-page browse sheet over the proceedings.

For each completed qNN.md it extracts the question, the advisory recommendation,
the confidence, and the "when the alternative is the better choice" conditions (the
flip conditions), so a reader can scan all 25 decisions and jump into the full
proceeding when one is worth reading. Pure text extraction — no models.

    python eval/build_index.py
"""

from __future__ import annotations

import os
import re

_HERE = os.path.dirname(__file__)
OUT_DIR = os.path.join(_HERE, "..", "eval_runs")


def _between(text, start, end):
    """Return text between the `start` marker and the first `end` marker after it."""
    i = text.find(start)
    if i == -1:
        return ""
    i += len(start)
    j = text.find(end, i)
    return text[i:j if j != -1 else None].strip()


def _conditions(opinion):
    block = _between(
        opinion,
        "WHEN THE ALTERNATIVE IS THE BETTER CHOICE:",
        "CONSIDERATIONS TO STILL WEIGH:",
    )
    return [re.sub(r"^[-\s]+", "", ln).strip()
            for ln in block.splitlines() if ln.strip().startswith("-")]


def parse(md):
    # Question: first "## Qn: ..." heading.
    qm = re.search(r"^## Q\d+:\s*(.+)$", md, re.MULTILINE)
    question = qm.group(1).strip() if qm else "(unknown)"
    # Opinion block lives in a fenced code block after the opinion heading.
    op = _between(md, "THE COURT'S OPINION", "```")
    rec = _between(op, "RECOMMENDATION:", "CONFIDENCE:") or "(no recommendation parsed)"
    conf_m = re.search(r"CONFIDENCE:\s*([0-9.]+)", op)
    conf = conf_m.group(1) if conf_m else "?"
    return question, " ".join(rec.split()), conf, _conditions(op)


def main():
    pages = sorted(f for f in os.listdir(OUT_DIR) if re.fullmatch(r"q\d\d\.md", f))
    md = [
        "# Decision Index — 25 technical proceedings\n",
        "One row per question: the court's advisory recommendation, its confidence, "
        "and the conditions under which the *other* option is the better call. Open "
        "the linked `qNN.md` for the full verbatim proceeding.\n",
    ]
    for pf in pages:
        n = int(pf[1:3])
        with open(os.path.join(OUT_DIR, pf), encoding="utf-8") as fh:
            question, rec, conf, conds = parse(fh.read())
        md.append(f"## Q{n} · [full proceeding]({pf})\n")
        md.append(f"**Question.** {question}\n")
        md.append(f"**Recommendation** (confidence {conf}): {rec}\n")
        if conds:
            md.append("**The alternative wins when:**")
            md += [f"- {c}" for c in conds]
            md.append("")
    out = os.path.join(OUT_DIR, "INDEX.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"Wrote {os.path.relpath(out)} ({len(pages)} questions).")


if __name__ == "__main__":
    main()
