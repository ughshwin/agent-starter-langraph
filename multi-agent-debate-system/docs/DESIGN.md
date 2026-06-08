# Multi-Agent Debate System — Design Spec

## Purpose

Given a technical decision framed as a question, run an adversarial debate between
three agents and produce a structured, nuanced verdict a senior engineer would
find genuinely useful for making the decision.

- **Proposer** — argues *for* the position.
- **Opposer** — argues *against* it.
- **Judge** — steers the debate each round and synthesises a final verdict.

This is a pure reasoning exercise: **no tools, no retrieval, no human in the loop,
no streaming.** The learning target is adversarial coordination, persistent
conflicting objectives, multi-round state management, and synthesis.

## Non-goals (from brief)

No real-time streaming, no mid-debate human input, max 3 rounds, no external tool
use, not an information-retrieval task.

## Orchestration — LangGraph state machine

```
START → proposer → opposer → judge_observe → [route_round]
                                                  ├─ more rounds → proposer  (loop)
                                                  └─ last round  → judge_verdict → END
```

- **Nodes:** `proposer`, `opposer`, `judge_observe` (per-round steering), and
  `judge_verdict` (final synthesis).
- **Conditional edge** `route_round` reads the round counter — termination, the
  hardest part of multi-agent design, is made explicit and unmissable here.
- Rounds: min 2, max 3 (configurable `--rounds`, default 3).

Per round: Proposer argues → Opposer rebuts → Judge observes what is missing and
injects a steering directive used by the next round. After the final round the
Judge synthesises the `Verdict`.

## Three models, one per role (heterogeneous by design)

| Role | Default model | Rationale |
|------|---------------|-----------|
| Proposer | `llama3.1:latest` | assertive advocate |
| Opposer  | `qwen2.5:7b`      | different family → genuine disagreement, not an echo |
| Judge    | `qwen3:8b` (thinking mode) | only reasoning model → deep synthesis where it matters |

Using **different model families** is itself a defence against the failure mode
where two same-model agents converge (brief Decision 2): different training
distributions produce genuinely different positions. The Judge gets the single
strongest reasoning model because synthesis is the hardest capability.

Only one ~8B model fits the 4 GB GPU at a time, so Ollama swaps models per turn
(a few seconds of reload). Acceptable for a non-real-time batch debate;
`--single-model M` collapses all three roles onto one model for speed.

## The brief's five decisions — how this design answers them

1. **History exposure (hybrid).** Round 1 sends the full debate so far; rounds
   2–3 send only the opponent's last argument plus the Judge's steering. Coherent
   opening, dynamic direct engagement after. Configurable: `hybrid|full|last`.
2. **Preventing agreement (role commitment + heterogeneity).** Each agent's
   system prompt orders it to steelman its assigned side regardless of personal
   assessment. Reinforced by different model families per side.
3. **A useful Judge (forced structure).** The `Verdict` schema forces the Judge
   to name strongest/weakest arguments, underlying assumptions, and — most
   importantly — the `conditions` under which each side is correct. A verdict that
   "averages" is treated as a failure.
4. **Active Judge (per-round steering).** After each round the Judge writes an
   observation that names unaddressed dimensions (e.g. operational complexity)
   and is injected into the next round's prompts. The Judge participates, not
   just evaluates.
5. **Evaluation (manual rubric).** `eval/` runs ≥3 technical questions and scores
   each output against `eval/criteria.md`: internal consistency, direct
   engagement with the opponent's strongest points, and decision-usefulness.

## State

```python
class DebateState(TypedDict):
    question: str
    round: int                                   # current round, 1-based
    max_rounds: int
    history_mode: str                            # hybrid | full | last
    proposer_arguments: Annotated[list[RoundArgument], add]
    opposer_arguments:  Annotated[list[RoundArgument], add]
    judge_observations: Annotated[list[str], add]
    final_verdict: Verdict | None
```

Reducer-based list fields let each node return only its new item; LangGraph
accumulates. The `round` counter is incremented in `judge_observe`; `route_round`
reads it to loop or finish.

## Structured output (reliability core)

Every agent output is constrained with Ollama's `format=<json-schema>` and
validated with Pydantic — the debate analog of the research agent's tool-call
recovery problem, solved at the decode layer instead of by post-hoc parsing.

- Proposer / Opposer → `ArgumentPayload {argument, rebuttals_to}` (round attached
  in code).
- Judge verdict → `Verdict` with `think=True` (reasoning in `message.thinking`,
  final answer grammar-constrained to the schema).
- Judge observation → free text with `think=True`.

On a validation failure the client retries with the error fed back, then falls
back to lenient JSON extraction; the runner degrades to a labelled partial
verdict rather than crashing.

## Reliability features (carried from the research-agent experience)

- Per-LLM-call timeout (only thing that stops a hung generation).
- Validation-retry with error feedback; lenient JSON extraction fallback.
- `num_predict` caps per role (large for the thinking Judge, small for advocates).
- History bounding so context can't explode across rounds.
- Graceful degradation to `[INCOMPLETE]` labelled verdict on repeated failure.
- Preflight: Ollama reachable and every role model pulled, with a fix hint.
- UTF-8 stdout; live reasoning trace (ROUND / PROPOSER / OPPOSER / JUDGE).

## Layout

```
multi-agent-debate-system/
  main.py                  CLI entry
  requirements.txt
  src/debate/
    config.py              Settings, per-role models, tunables
    schemas.py             Pydantic models + DebateState
    llm.py                 Ollama client wrapper (json/think/timeout/retry)
    prompts.py             role-commitment prompts + history builders
    agents.py              proposer / opposer / judge node factory (DI for tests)
    graph.py               StateGraph wiring + routing
    runner.py              run_debate(), trace logging, degradation
  eval/
    questions.py           ≥3 technical decision questions
    run_eval.py            batch harness
    criteria.md            manual scoring rubric (Decision 5)
  tests/                   schemas / parsing / graph (FakeLLM, no model needed)
  docs/
    DESIGN.md              this file
    TECHNICAL_DEEP_DIVE.md decisions, failure modes, measured state
```
