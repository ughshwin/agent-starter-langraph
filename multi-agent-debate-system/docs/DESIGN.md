# Multi-Agent Debate System — Design Spec (Courtroom Proceeding)

## Purpose

Given a technical decision framed as a question, put it **on trial**: run an
adversarial proceeding between three agents and produce a structured, advisory
opinion a senior engineer would find genuinely useful for making the decision.

- **Defence counsel** — argues *for* the proposition.
- **Prosecution counsel** — argues *against* it.
- **Judge** — presides: directs each round of cross-examination, then delivers an
  *advisory opinion* (a strong recommendation, not a binding winner declaration —
  the reader is the final decision-maker).

This is a pure reasoning exercise: **no tools, no retrieval, no human in the loop,
no streaming.** The learning target is adversarial coordination, persistent
conflicting objectives, multi-phase state management, and synthesis.

## Non-goals (from brief)

No real-time streaming, no mid-proceeding human input, no external tool use, not an
information-retrieval task. (The brief's original 3-round cap has been lifted on
request — see "Round count" below; min 2, max 20.)

## Orchestration — LangGraph state machine

```
frame → defence_opening → prosecution_opening → judge_direct ─┐
                                                              │ (route_examination)
        ┌─ round ≤ max ── defence_examine → prosecution_examine ┘
        │                          │
        │                    judge_direct  (loop)
        └─ else → defence_closing → prosecution_closing → verdict → END
```

The proceeding has four phases: **opening statements → cross-examination →
closing statements → advisory opinion.**

- **Framing (pre-proceeding, in `runner.frame_debate`):** derives the two explicit,
  mutually-exclusive positions counsel defend, so an "A or B" question (which has no
  single "proposition") still pins each side to a concrete opposite stance. See
  Decision 2. Degrades to generic stances if the call fails.
- **Nodes:** `defence_opening` / `prosecution_opening`, `defence_examine` /
  `prosecution_examine`, `judge_direct` (per-round bench direction + round
  counter), `defence_closing` / `prosecution_closing`, `verdict`.
- **Hub + conditional edge.** `judge_direct` is the hub: it directs the next round,
  increments the examination counter, and `route_examination` reads that counter to
  loop or move to closing — termination, the hardest part of multi-agent design,
  made explicit in one place. The counter starts at 0; the first `judge_direct`
  (after openings) advances it to 1, so exactly `max_rounds` rounds run.
- **Round count:** min 2, max 20, default 6 cross-examination rounds (`--rounds`).
  `recursion_limit` scales as `4*max_rounds + 20`.

Each examination round: each counsel answers the opponent's last question, rebuts,
advances a NEW argument, and puts one pointed question back; the Judge then directs
what the next round must cover. After closing statements the Judge delivers the
advisory `Verdict`.

## Three reasoning models, one per role — each from a different lab

| Role | Default model | Lab | Rationale |
|------|---------------|-----|-----------|
| Defence | `gpt-oss:20b`     | OpenAI   | reasoning advocate |
| Prosecution | `deepseek-r1:14b` | DeepSeek | reasoning advocate, different lab → genuine disagreement |
| Judge    | `qwen3:32b` (thinking) | Alibaba | the bench — largest model on the hardest job |

Using models from **three different labs** is the strong form of the Decision-2
defence against convergence: different training distributions produce genuinely
different positions, far more so than two checkpoints of one family. Every role is
a *reasoning* model and thinks before speaking (`advocate_think`,
`enable_thinking`), which is what makes a deep proceeding substantive.
The Judge gets the largest model because synthesis is the hardest capability.

On the reference 48 GB GPU the 32B judge stays resident and the two ~13 GB counsel
alternate (judge + both counsel + KV cache slightly exceed VRAM at 16k context), so
only the counsel incur a per-turn reload — the judge never swaps. On a small GPU
everything swaps; `--single-model M` collapses all three roles onto one model.

## The brief's five decisions — how this design answers them

1. **History exposure (hybrid).** The first examination round sends the full court
   record; later rounds send only the opponent's last turn plus the bench's
   direction. Coherent opening, dynamic direct engagement after, and bounded
   context that does not explode across rounds. Configurable: `hybrid|full|last`.
2. **Preventing agreement (explicit positions + anti-defection + different labs).**
   A pre-proceeding framing step assigns each counsel a concrete, mutually-exclusive
   position (the fix for "A or B" questions that have no single proposition, where
   two helpful models otherwise both drift to the conventional answer). The advocate
   contract then orders each counsel to steelman its *assigned* position and
   *explicitly forbids defection* — observed empirically: over a long debate a
   reasoning model otherwise reasons toward the conventional answer and switches
   sides. Reinforced by using three different labs' models.
3. **A useful Judge (forced structure).** The `Verdict` schema forces the Judge to
   name the `grounds`, where the alternative is weaker, and — most importantly — the
   `conditions` under which the alternative is the better choice. An opinion that
   "averages" is treated as a failure; so is one that declares an absolute winner —
   it must be advisory.
4. **Active Judge (presiding).** The Judge `judge_direct`s before each examination
   round, naming unaddressed dimensions (operational complexity, migration risk,
   security, team capability), injected into the next round. The Judge runs the
   proceeding, not just scores it.
5. **Evaluation (manual rubric).** `eval/` runs ≥3 technical questions and scores
   each output against `eval/criteria.md`: role commitment, direct engagement with
   the opponent's strongest points, internal consistency, active judge, and
   decision-usefulness.

## State

```python
class DebateState(TypedDict):
    question: str
    defence_position: str                        # explicit stance set at framing
    prosecution_position: str                    # explicit opposite stance
    round: int                                   # examination round (0 before it opens)
    max_rounds: int                              # number of cross-examination rounds
    history_mode: str                            # hybrid | full | last
    record: Annotated[list[CourtRecordEntry], add]   # the full court transcript
    judge_directions: Annotated[list[str], add]      # the bench's per-round directions
    final_verdict: Verdict | None                    # the advisory opinion
```

The reducer on `record` lets each node return only its new entry; LangGraph
accumulates the full transcript. The `round` counter is incremented in
`judge_direct`; `route_examination` reads it to loop or move to closing.

## Structured output (reliability core)

Every agent output is constrained with Ollama's `format=<json-schema>` and
validated with Pydantic — solved at the decode layer instead of by post-hoc
parsing.

- Framing → `DebateFraming {defence_position, prosecution_position}`.
- Opening / closing → `Statement {statement, key_points}` with `think=True`.
- Cross-examination → `ExaminationTurn {response, question_to_opponent,
  rebuttals_to}` with `think=True` (round attached in code; reasoning trace in
  `message.thinking`, JSON answer grammar-constrained to the schema).
- Judge opinion → `Verdict` with `think=True`.
- Bench direction → free text with `think=True`.

Because the reasoning trace counts against `num_predict`, the per-call token
budgets are large (counsel 4000, opinion 6000) — a small cap would truncate the
model mid-thought, leaving no tokens for the JSON answer.

On a validation failure the client retries with the error fed back, then falls
back to lenient JSON extraction; the runner degrades to a labelled partial entry or
opinion rather than crashing.

## Reliability features (carried from the research-agent experience)

- Per-LLM-call timeout (only thing that stops a hung generation).
- Validation-retry with error feedback; lenient JSON extraction fallback.
- `num_predict` caps per role, all sized to hold the reasoning trace + the answer.
- History bounding so context can't explode across rounds.
- Graceful degradation to a labelled `[INCOMPLETE]` opinion on repeated failure.
- Preflight: Ollama reachable and every role model pulled, with a fix hint.
- UTF-8 stdout; live trace (PHASE / ROUND / DEFENCE / PROSECUTION / JUDGE).

## Layout

```
multi-agent-debate-system/
  main.py                  CLI entry
  requirements.txt
  src/debate/
    config.py              Settings, per-role models, tunables
    schemas.py             Pydantic wire schemas + DebateState (court record)
    llm.py                 Ollama client wrapper (json/think/timeout/retry)
    prompts.py             framing + advocate contract + per-phase builders + judge
    agents.py              opening / examination / closing / judge node factory (DI)
    graph.py               StateGraph wiring + examination routing
    runner.py              run_debate(), framing, trace, advisory opinion
  eval/
    questions.py           ≥3 technical decision questions
    run_eval.py            batch harness
    criteria.md            manual scoring rubric (Decision 5)
  tests/                   schemas / parsing / graph (FakeLLM, no model needed)
  docs/
    DESIGN.md              this file
    TECHNICAL_DEEP_DIVE.md decisions, failure modes, measured state
```
