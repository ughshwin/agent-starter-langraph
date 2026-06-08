# Multi-Agent Debate System — Technical Deep Dive

An adversarial three-agent **courtroom proceeding** built on **LangGraph**, running
entirely on **local Ollama models**. A technical decision is put on trial: Defence
counsel argues for it, Prosecution counsel against it, across opening statements,
bounded cross-examination, and closing statements; a Judge presides — directing
each round and delivering an *advisory opinion* (a strong recommendation, not a
binding winner declaration). This document explains the design decisions, the
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

**Non-goals (from the brief):** no streaming, no mid-debate human input, no
external tools, not information retrieval. It is a pure reasoning exercise. (The
brief's original 3-round cap has been lifted on request to support a deep internal
debate — default 8 rounds, min 2, max 20.)

---

## 2. Architecture

### The graph

```
frame → defence_opening → prosecution_opening → judge_direct ─┐
                                                              │ (route_examination)
        ┌─ round ≤ max ── defence_examine → prosecution_examine ┘
        │                          │
        │                    judge_direct  (loop)
        └─ else → defence_closing → prosecution_closing → verdict → END
```

LangGraph owns the control flow. Eight nodes (`graph.py`, `agents.py`):

| Node | Role | Output into state |
|------|------|-------------------|
| `defence_opening` / `prosecution_opening` | opening statements | append a `Statement` record entry |
| `defence_examine` / `prosecution_examine` | cross-examine | append an `ExaminationTurn` entry |
| `judge_direct` | direct next round | appends a direction, **increments `round`** |
| `defence_closing` / `prosecution_closing` | closing statements | append a `Statement` entry |
| `verdict` | advisory opinion | sets `final_verdict` |

`route_examination` is the **entire termination policy in one function** — the
brief calls termination "the hardest part of multi-agent design", so it lives in
one obvious place. `judge_direct` is the hub: it increments the round counter, so
by the time we route it already names the round we are about to run;
`route_examination` loops to a new examination round while `round ≤ max_rounds`,
else hands off to the closing statements and verdict.

### State (`schemas.py`)

`DebateState` is a `TypedDict` threaded through every node. The `record` and
`judge_directions` fields use `Annotated[list[...], add]` **reducers**, so each
node returns only its new entry and LangGraph accumulates the full court
transcript — nodes never read-modify-write the whole list.

```python
class DebateState(TypedDict):
    question: str
    defence_position: str                        # explicit stance set at framing
    prosecution_position: str                    # explicit opposite stance
    round: int                                   # exam round, bumped in judge_direct
    max_rounds: int
    history_mode: str                            # hybrid | full | last
    record: Annotated[list[CourtRecordEntry], add]   # full transcript
    judge_directions: Annotated[list[str], add]
    final_verdict: Verdict | None
```

This is the multi-agent analog of the research agent's "the message list *is* the
memory": here the typed, reducer-managed state *is* the debate's working memory, and
keeping it correct and bounded is the central concern.

---

## 3. The brief's five decisions

### Decision 1 — How much history does each agent see? **Hybrid.**

Full court record for the first examination round (coherent opening), opponent's
last turn only for later rounds (forces direct engagement, keeps context bounded,
avoids counsel restating earlier points). Implemented in
`prompts.py::build_examination_user`; selectable with `--history {hybrid,full,last}`
so the trade-off can actually be A/B'd, which is what the brief asks for.

The Judge's per-round direction is injected **independently of the history mode** —
even in `last` mode, every examination round receives the latest bench direction.

### Decision 2 — How do you stop both counsel agreeing? **Explicit positions + anti-defection + different labs.**

Three levers:

1. **Explicit assigned positions (framing).** Before the proceeding a framing step
   derives two concrete, mutually-exclusive stances and pins one to each counsel.
   This fixes the trap where an "A or B" question has no single "proposition", so two
   helpful models told to argue "for"/"against" both drift to the conventionally-
   correct answer. Observed live: on the brief's own `"build in-house or use
   Auth0?"` phrasing, *both* counsel argued for Auth0 in round 1 until framing was
   added — after which the Defence commits to in-house and it is genuinely two-sided.
2. **Anti-defection role commitment.** Each counsel's system prompt orders it to
   make the strongest case for its *assigned* position and *explicitly forbids
   switching sides*, even partially, even in later rounds — and tells it to ignore an
   opponent who mistakenly argues its side. This was empirically necessary: in an
   early 8-round run the `deepseek-r1` prosecution **defected to the in-house side in
   5 of 8 rounds** before the clause was added; afterward both counsel held their
   positions across all rounds. The single most important piece of prompt design.
3. **Different labs per role.** Defence is `gpt-oss:20b` (OpenAI), Prosecution is
   `deepseek-r1:14b` (DeepSeek), Judge is `qwen3:32b` (Alibaba). Three different
   labs' training distributions reduce convergence far more than two checkpoints of
   one family would.

### Decision 3 — What makes the Judge useful, not an averager? **Forced structure, advisory tone.**

A Judge that says "both sides have good points, it depends" is worthless — but so
is one that bangs a gavel and declares an absolute winner. The opinion is
*advisory*. The `Verdict` schema *forces* the Judge to give a recommendation phrased
as counsel ("I suggest A because ..."), the `grounds` for it, `why_alternative_is_weaker`,
and — the most important field — `conditions`: when the alternative is actually the
better choice instead. Structure is enforced at the decode layer (`format=<json
schema>`), so the Judge cannot dodge it.

### Decision 4 — How does the Judge influence the debate? **It presides.**

Before every examination round, `judge_direct` names the dimensions the proceeding
has under-served (operational complexity, migration risk, security, team capability)
and directs both counsel to examine them next. That direction is fed into the next
round's prompts. The Judge runs the proceeding rather than only scoring it, which
produces richer final opinions.

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

- Counsel emit a `Statement` (opening/closing) or an `ExaminationTurn {response,
  question_to_opponent, rebuttals_to}`; the round number and phase are attached in
  code, never asked of the model (one less thing to get wrong).
- The Judge emits a `Verdict` with `think=True` — its reasoning goes to
  `message.thinking` while the final answer stays schema-constrained.

**Validation-retry with feedback.** If output fails to validate, `llm.py` re-asks
with the error made explicit, up to `validation_retries` times, before giving up.

**Lenient extraction fallback.** If a server ignores `format=`, `extract_model`
recovers a valid object from embedded JSON and tolerates the invalid backslash
escapes small models emit (carried directly from the research agent).

**Thinking-mode guard.** If a model rejects the `think` parameter, the call is
retried once without it rather than failing the proceeding.

**Per-call timeouts.** Each LLM call has its own timeout (longer for the thinking
Judge) — the only thing that can stop a single hung generation on a CPU/GPU split.

**Graceful degradation.** A failed counsel call becomes a labelled placeholder
record entry so the proceeding still reaches an opinion; a failed opinion becomes a
labelled `[INCOMPLETE]` Verdict. The graph **always** terminates with a
`final_verdict` — never a crash, never a hang, never `None`.

**Preflight.** Before running, `runner.preflight` checks Ollama is reachable and
every role model is pulled, printing `ollama pull ...` hints for any that are
missing.

**Console hygiene.** UTF-8 stdout (thinking models emit non-ASCII that crashes the
cp1252 Windows console otherwise); a live `PHASE / ROUND / DEFENCE / PROSECUTION /
JUDGE` trace so you can watch the proceeding and the bench's directions as they
happen.

---

## 5. Why three reasoning models from three labs, and the cost

Three different labs' reasoning models make the proceeding genuinely adversarial
(Decision 2) and give the Judge — the hardest job — the largest model. Every role
*thinks* before it answers, which is what makes a deep proceeding substantive rather
than three models pattern-matching. The cost: on the reference 48 GB GPU the 32B
judge stays resident but the two ~13 GB counsel alternate (judge + both counsel + KV
cache at 16k context slightly exceed VRAM), so the counsel incur a per-turn reload
while the judge never swaps. On a small GPU everything swaps; `--single-model M`
removes swaps entirely when speed matters. A second cost is latency: reasoning
traces are 2–3× the tokens of a direct answer, so a full proceeding is a
multi-minute batch job, not interactive — which the brief permits.

---

## 6. Testing

`tests/` drives the **entire LangGraph against a `FakeLLM`** — no Ollama, no models
loaded, sub-second. Because `agents.py`/`graph.py` take the client by injection,
the fake simply returns valid schema instances and records calls. The graph tests
assert the coordination the brief targets: the phase order (opening → examination →
closing → opinion), correct number of examination rounds, the round counter
advancing past `max_rounds` to reach closing, record accumulation, a `Verdict` at
the end, and that the three role models are each actually used. The routing policy
is unit-tested directly, and the parsing/recovery and schema-validation paths have
their own tests. `python -m pytest` → 15 tests.

---

## 7. How this differs from a single agent

A single model asked "in-house or Auth0?" gives one fluent, plausibly-balanced
answer whose hidden assumptions you never see. The proceeding forces the *strongest*
case for each side to be stated explicitly, forces each side to engage the other's
best points (cross-examination), and makes a dedicated Judge convert the clash into
an advisory opinion with conditions. The value is not that three models are smarter
than one — it is that adversarial structure surfaces the trade-off space a single
helpful answer flattens.

---

## 8. Configuration & tunables

In `config.py::Settings`:

| Knob | Default | Meaning |
|------|---------|---------|
| `defence_model` | `gpt-oss:20b` | Defence counsel (OpenAI) |
| `prosecution_model` | `deepseek-r1:14b` | Prosecution counsel (DeepSeek) |
| `judge_model` | `qwen3:32b` | the bench: direction + opinion, thinking (Alibaba) |
| `max_rounds` | 6 | cross-examination rounds (2..20) |
| `history_mode` | `hybrid` | hybrid / full / last |
| `advocate_think` / `enable_thinking` | True / True | reason before answering, all roles |
| `advocate_num_predict` | 4000 | token cap per advocate turn (trace + answer) |
| `judge_verdict_num_predict` | 6000 | token cap for thinking + verdict |
| `advocate_timeout` / `judge_timeout` | 600 / 900 s | per-call timeouts |
| `validation_retries` | 2 | re-asks on schema-validation failure |

CLI (`main.py`): `--rounds`, `--history`, `--single-model`, per-role `--*-model`,
`--quiet`, `--json`.

---

## 9. Known limitations & possible future work

- **No self-consistency.** One proceeding, no voting across samples; a stronger
  Judge model lifts opinion quality with no code change.
- **The bench's final direction is unused.** `judge_direct` runs once more after the
  last examination round; that direction informs nothing (closing follows). Harmless
  but one wasted Judge call per proceeding.
- **History `last` mode can lose the thread** on a long argument — the brief's own
  caveat; hybrid is the default for this reason.
- **Counsel model swaps add wall-clock** when the 32B judge plus both counsel exceed
  VRAM (the 48 GB reference case at 16k context). Lowering the context window, using
  the `:14b` judge, or `--single-model` removes the swaps; the coordination logic is
  unchanged either way.
- **Argument novelty thins out over many rounds.** With many cross-examination
  rounds counsel can start repeating once the genuinely new points are exhausted;
  the Judge's direction mitigates but does not eliminate this. Fewer rounds often
  gives a comparable opinion in less time.
