# Multi-Agent Debate System — Technical Deep Dive

An adversarial three-agent debate built on **LangGraph**, running entirely on
**local Ollama models**. A Proposer and an Opposer argue opposite sides of a
technical decision across bounded rounds; a Judge steers the debate each round and
synthesises a structured verdict. This document explains the design decisions, the
reliability engineering, and how it differs from a single-agent system.

It is written to be read alongside the source under [`src/debate/`](../src/debate).

This project is the second in a series; it deliberately reuses the reliability
lessons from a from-scratch ReAct research agent (per-call timeouts, structured-
output validation with graceful degradation, UTF-8 console, a live reasoning
trace) and applies them to a *multi-agent coordination* problem instead of a
*tool-use* one.

---

## 1. What this is

Given a technical decision framed as a question ("build auth in-house or use
Auth0?"), the system runs a debate and returns a `Verdict` — a recommendation with
a calibrated confidence, the factors that drove it, the **conditions** under which
each choice is correct, and the strongest dissenting considerations.

**Goal:** understand adversarial multi-agent coordination — agents with persistent
*conflicting* objectives, state managed across rounds, and synthesis of conflicting
inputs into a nuanced output.

**Non-goals (from the brief):** no streaming, no mid-debate human input, max 3
rounds, no external tools, not information retrieval. It is a pure reasoning
exercise.

---

## 2. Architecture

### The graph

```
START → proposer → opposer → judge_observe → [route_round]
                                                ├─ round ≤ max → proposer  (loop)
                                                └─ else        → judge_verdict → END
```

LangGraph owns the control flow. Four nodes (`graph.py`, `agents.py`):

| Node | Role | Output into state |
|------|------|-------------------|
| `proposer` | argue FOR | appends a `RoundArgument` |
| `opposer` | argue AGAINST | appends a `RoundArgument` |
| `judge_observe` | steer next round | appends an observation, **increments `round`** |
| `judge_verdict` | final synthesis | sets `final_verdict` |

`route_round` is the **entire termination policy in one function** — the brief
calls termination "the hardest part of multi-agent design", so it lives in one
obvious place instead of being scattered. The round counter is bumped inside
`judge_observe`, so by the time we route it already names the round we are about to
run; `route_round` loops while `round ≤ max_rounds`, else hands off to the verdict.

### State (`schemas.py`)

`DebateState` is a `TypedDict` threaded through every node. The three list fields
use `Annotated[list[...], add]` **reducers**, so each node returns only its new item
and LangGraph accumulates — nodes never read-modify-write the whole list.

```python
class DebateState(TypedDict):
    question: str
    round: int                                   # 1-based, bumped in judge_observe
    max_rounds: int
    history_mode: str                            # hybrid | full | last
    proposer_arguments: Annotated[list[RoundArgument], add]
    opposer_arguments:  Annotated[list[RoundArgument], add]
    judge_observations: Annotated[list[str], add]
    final_verdict: Verdict | None
```

This is the multi-agent analog of the research agent's "the message list *is* the
memory": here the typed, reducer-managed state *is* the debate's working memory, and
keeping it correct and bounded is the central concern.

---

## 3. The brief's five decisions

### Decision 1 — How much history does each agent see? **Hybrid.**

Full debate for round 1 (coherent opening), opponent's last argument only for
rounds 2–3 (forces direct engagement, keeps context bounded, avoids agents
restating earlier points). Implemented in `prompts.py::_context_for`; selectable
with `--history {hybrid,full,last}` so the trade-off can actually be A/B'd, which
is what the brief asks for.

The Judge's per-round steering is injected **independently of the history mode** —
even in `last` mode, rounds ≥ 2 always receive the latest Judge observation.

### Decision 2 — How do you stop both agents agreeing? **Role commitment + heterogeneity.**

Two levers:

1. **Prompted role commitment.** Each advocate's system prompt orders it to make
   the strongest case for its assigned side *even if it personally believes the
   other view has merit*, and forbids "both sides have a point". This is the single
   most important piece of prompt design in the project (`prompts.py`).
2. **Different model families per side.** Proposer is `llama3.1`, Opposer is
   `qwen2.5`. Different training distributions reduce the convergence you get when
   one model argues with itself. The Judge runs a third model (`qwen3`).

### Decision 3 — What makes the Judge useful, not an averager? **Forced structure.**

A Judge that says "both sides have good points, it depends" is worthless. The
`Verdict` schema *forces* the Judge to name strongest/weakest arguments, the
assumptions each side rests on, a concrete recommendation, and — the most important
field — `conditions`: when the recommendation holds and when the opposite choice
becomes correct instead. Structure is enforced at the decode layer (`format=<json
schema>`), so the Judge cannot dodge it.

### Decision 4 — How does the Judge influence the debate? **Active, per-round steering.**

After every round, `judge_observe` writes an observation naming the dimensions the
round under-served (operational complexity, migration risk, security, team
capability) and directs both sides to engage them next round. That observation is
fed into the next round's advocate prompts. The Judge participates rather than only
scoring, which produces richer final verdicts.

### Decision 5 — How do you evaluate quality? **A manual rubric, defined first.**

Debate quality is subjective, so `eval/criteria.md` defines it *before* running:
role commitment, direct engagement with the opponent's strongest points, internal
consistency, active-Judge steering, and — the real test — whether a senior engineer
would find the verdict useful for deciding. `eval/run_eval.py` runs the question
battery and saves full transcripts to `eval_runs/` for hand-scoring.

---

## 4. Reliability engineering

Structured output is to this project what tool-call recovery was to the research
agent: the place a small local model breaks. The defences, input to output:

**Structured output (the core).** Every agent output is constrained with Ollama's
`format=<pydantic json schema>` (grammar-constrained decoding) and validated with
Pydantic. Solving it at the decode layer is far more reliable than parsing prose
after the fact.

- Advocates emit `ArgumentPayload {argument, rebuttals_to}`; the round number is
  attached in code, never asked of the model (one less thing to get wrong).
- The Judge emits a `Verdict` with `think=True` — its reasoning goes to
  `message.thinking` while the final answer stays schema-constrained.

**Validation-retry with feedback.** If output fails to validate, `llm.py` re-asks
with the error made explicit, up to `validation_retries` times, before giving up.

**Lenient extraction fallback.** If a server ignores `format=`, `extract_model`
recovers a valid object from embedded JSON and tolerates the invalid backslash
escapes small models emit (carried directly from the research agent).

**Thinking-mode guard.** `think=True` is only sent to the Judge; if any model
rejects the parameter, the call is retried once without it rather than failing the
debate.

**Per-call timeouts.** Each LLM call has its own timeout (longer for the thinking
Judge) — the only thing that can stop a single hung generation on a CPU/GPU split.

**Graceful degradation.** A failed advocate call becomes a labelled placeholder
argument so the debate still reaches a verdict; a failed verdict becomes a labelled
`[INCOMPLETE]` Verdict. The graph **always** terminates with a `final_verdict` —
never a crash, never a hang, never `None`.

**Preflight.** Before running, `runner.preflight` checks Ollama is reachable and
every role model is pulled, printing `ollama pull ...` hints for any that are
missing.

**Console hygiene.** UTF-8 stdout (thinking models emit non-ASCII that crashes the
cp1252 Windows console otherwise); a live `ROUND / PROPOSER / OPPOSER / JUDGE`
trace so you can watch the debate and the Judge's steering as they happen.

---

## 5. Why three models, and the cost

Heterogeneous models make the debate genuinely adversarial (Decision 2) and give
the Judge — the hardest job — the strongest reasoning model. The cost on a 4 GB GPU
is that only one ~8B model is resident at a time, so Ollama unloads and reloads
between turns (a few seconds per swap). For a non-real-time batch debate that is an
acceptable trade; `--single-model M` removes swaps entirely when speed matters.

---

## 6. Testing

`tests/` drives the **entire LangGraph against a `FakeLLM`** — no Ollama, no models
loaded, sub-second. Because `agents.py`/`graph.py` take the client by injection,
the fake simply returns valid schema instances and records calls. The graph tests
assert the coordination the brief targets: correct round count, the round counter
advancing past `max_rounds` to terminate, list accumulation, a `Verdict` at the
end, and that the three role models are each actually used. The routing policy is
unit-tested directly, and the parsing/recovery and schema-validation paths have
their own tests. `python -m pytest` → 14 tests.

---

## 7. How this differs from a single agent

A single model asked "in-house or Auth0?" gives one fluent, plausibly-balanced
answer whose hidden assumptions you never see. The debate forces the *strongest*
case for each side to be stated explicitly, forces each side to engage the other's
best points (`rebuttals_to`), and makes a dedicated synthesiser convert the clash
into conditions. The value is not that three models are smarter than one — it is
that adversarial structure surfaces the trade-off space a single helpful answer
flattens.

---

## 8. Configuration & tunables

In `config.py::Settings`:

| Knob | Default | Meaning |
|------|---------|---------|
| `proposer_model` | `llama3.1:latest` | advocate FOR |
| `opposer_model` | `qwen2.5:7b` | advocate AGAINST |
| `judge_model` | `qwen3:8b` | steering + synthesis (thinking) |
| `max_rounds` | 3 | debate rounds (2 or 3) |
| `history_mode` | `hybrid` | hybrid / full / last |
| `advocate_num_predict` | 900 | token cap per advocate turn |
| `judge_verdict_num_predict` | 3000 | token cap for thinking + verdict |
| `advocate_timeout` / `judge_timeout` | 240 / 420 s | per-call timeouts |
| `validation_retries` | 2 | re-asks on schema-validation failure |

CLI (`main.py`): `--rounds`, `--history`, `--single-model`, per-role `--*-model`,
`--quiet`, `--json`.

---

## 9. Known limitations & possible future work

- **No self-consistency.** One debate, no voting across samples; a stronger Judge
  model lifts verdict quality with no code change.
- **Judge observation is always run**, even on the final round where it cannot
  steer a next round (it still informs the verdict). A micro-optimisation would
  skip it on the last round.
- **History `last` mode can lose the thread** on a long argument — the brief's own
  caveat; hybrid is the default for this reason.
- **Model swaps dominate wall-clock** on a 4 GB GPU. `--single-model` or more VRAM
  removes this; the coordination logic is unchanged either way.
