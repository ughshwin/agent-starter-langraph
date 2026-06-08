# Proceeding Evaluation Criteria (brief Decision 5)

Quality is subjective, so define it before running. Score each proceeding's output
against these criteria **manually** — there is no automatic grader.

## Criteria

For each question, score 1–5 on each axis:

1. **Role commitment** — Did Defence and Prosecution each fully argue their assigned
   side across *every* phase (opening, examination, closing) without conceding,
   drifting into "both sides have a point", or switching sides? (The most common
   failure: helpful reasoning models converging or defecting over many rounds.)

2. **Direct engagement** — In cross-examination, did each side actually answer the
   opponent's pointed question and rebut their *strongest* specific points (visible
   in `rebuttals_to` / `question_to_opponent`), rather than ignoring them?

3. **Internal consistency** — Is each side's position coherent across rounds — no
   self-contradiction, no abandoning earlier claims?

4. **Active Judge** — Did the bench's per-round directions steer the next round
   toward genuinely unaddressed dimensions (operational complexity, migration
   risk, security, team capability), and did the proceeding shift in response?

5. **Decision usefulness (the real test)** — Reading the advisory `Verdict`, would a
   senior engineer say "this is actually useful for making the decision"? In
   particular: is the recommendation appropriately *advisory* (strong but not
   absolute); are the `grounds` and `why_alternative_is_weaker` specific; are the
   `conditions` precise enough to tell you *when* the alternative wins; and are the
   `dissenting_considerations` real (not boilerplate)?

## Pass bar

A proceeding "passes" if criteria 1, 2, and 5 are all ≥ 4. Criterion 5 is the one
that matters most — a structurally perfect proceeding with a useless opinion fails.

## Recording results

Run `python eval/run_eval.py` (optionally `--only N`). It writes the full trace
and verdict per question under `eval_runs/`. Fill in scores below per run.

| Q | Role commit | Engagement | Consistency | Active Judge | Useful | Pass? |
|---|-------------|------------|-------------|--------------|--------|-------|
| 1 |             |            |             |              |        |       |
| 2 |             |            |             |              |        |       |
| 3 |             |            |             |              |        |       |
| 4 |             |            |             |              |        |       |
