# Debate Evaluation Criteria (brief Decision 5)

Debate quality is subjective, so define it before running. Score each debate
output against these criteria **manually** — there is no automatic grader.

## Criteria

For each question, score 1–5 on each axis:

1. **Role commitment** — Did Proposer and Opposer each fully argue their assigned
   side without conceding or drifting into "both sides have a point"? (The most
   common failure: two helpful models converging.)

2. **Direct engagement** — From round 2 on, did each side actually rebut the
   opponent's *strongest* specific points (visible in `rebuttals_to`), rather than
   ignoring them and restating its own case?

3. **Internal consistency** — Is each side's position coherent across rounds — no
   self-contradiction, no abandoning earlier claims?

4. **Active Judge** — Did the Judge's per-round observations steer the next round
   toward genuinely unaddressed dimensions (operational complexity, migration
   risk, security, team capability), and did the debate actually shift in response?

5. **Decision usefulness (the real test)** — Reading the final `Verdict`, would a
   senior engineer say "this is actually useful for making the decision"? In
   particular: are the `conditions` specific enough to tell you *when* each choice
   is correct, and are the `dissenting_considerations` real (not boilerplate)?

## Pass bar

A debate "passes" if criteria 1, 2, and 5 are all ≥ 4. Criterion 5 is the one that
matters most — a structurally perfect debate with a useless verdict fails.

## Recording results

Run `python eval/run_eval.py` (optionally `--only N`). It writes the full trace
and verdict per question under `eval_runs/`. Fill in scores below per run.

| Q | Role commit | Engagement | Consistency | Active Judge | Useful | Pass? |
|---|-------------|------------|-------------|--------------|--------|-------|
| 1 |             |            |             |              |        |       |
| 2 |             |            |             |              |        |       |
| 3 |             |            |             |              |        |       |
| 4 |             |            |             |              |        |       |
