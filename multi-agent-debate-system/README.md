# Multi-Agent Debate System — a Courtroom Proceeding

A technical decision is put **on trial**. Three local reasoning agents — **each
from a different lab** — argue it out as a court: **Defence counsel** argues _for_
the proposition, **Prosecution counsel** argues _against_, and the **Judge**
presides — directing each round of cross-examination and finally delivering an
**advisory opinion** (a strong recommendation, _not_ a binding winner-takes-all
verdict — the reader is the final decision-maker). Built on **LangGraph** with
**local Ollama models only** — no API keys, no cloud, no tools.

> Adversarial coordination, persistent conflicting objectives, multi-phase state,
> and synthesis from conflicting inputs. See [`docs/DESIGN.md`](docs/DESIGN.md) and
> [`docs/TECHNICAL_DEEP_DIVE.md`](docs/TECHNICAL_DEEP_DIVE.md).

## How it works

```
frame → defence_opening → prosecution_opening → judge_direct ─┐
                                                              │ (route_examination)
        ┌─ round ≤ max ── defence_examine → prosecution_examine ┘
        │                          │
        │                    judge_direct  (loop)
        └─ else → defence_closing → prosecution_closing → verdict → END
```

The proceeding runs in four phases:

1. **Opening statements** — each counsel lays out its case.
2. **Cross-examination** — each round, both counsel answer the opponent's last
   question, rebut, advance a new argument, and put one pointed question back. The
   **Judge directs each round** toward dimensions still unaddressed (Decision 4).
3. **Closing statements** — each counsel sums up the record.
4. **The Judge's advisory opinion** — `Verdict { recommendation, confidence,
grounds, why_alternative_is_weaker, conditions, dissenting_considerations }`:
   _"I suggest A on these grounds (XYZ); the alternative B is likely weaker for
   these reasons (LMN); here is when B is the better call instead — but you decide."_

**Framing (Decision 2 fix):** before opening, a one-shot call derives the two
explicit, mutually-exclusive positions counsel defend (e.g. _"build in-house"_ vs
_"use Auth0"_). Relying on the words "for/against the proposition" silently
collapses for an _"A or B"_ question — it has no single proposition, so two helpful
models both drift to the conventionally-correct answer. Pinning each side of the
bar to a concrete assigned stance, plus an explicit **anti-defection clause** in
the advocate prompt, is what keeps the proceeding genuinely adversarial across many
rounds (reasoning models otherwise tend to "reason toward the conventional answer"
and quietly switch sides). Framing degrades to generic stances if the call fails.

## Three reasoning models — one per role, each from a different lab

| Role        | Default                | Lab      | Why                                                   |
| ----------- | ---------------------- | -------- | ----------------------------------------------------- |
| Defence     | `gpt-oss:20b`          | OpenAI   | reasoning advocate                                    |
| Prosecution | `deepseek-r1:14b`      | DeepSeek | reasoning advocate, different lab → real disagreement |
| Judge       | `qwen3:32b` (thinking) | Alibaba  | the bench — strongest model on the hardest job        |

**No two roles share a provider.** Three different labs' training is the strong
form of the Decision-2 defence against convergence: it makes genuine disagreement
far more likely than one model family talking to itself. Every role _reasons_
(thinks) before it speaks (`advocate_think` / `enable_thinking`), which is what
makes a deep proceeding substantive rather than three models pattern-matching.

> On the reference 48 GB GPU the 32B judge stays resident while the two ~13 GB
> counsel alternate (judge + both + KV cache slightly exceed VRAM at 16k context),
> so only the counsel incur a per-turn reload. Use the `:14b` judge or
> `--single-model` to remove swaps on smaller hardware.

## Setup

```bash
# 1. Ollama running, with the three models pulled:
ollama pull gpt-oss:20b
ollama pull deepseek-r1:14b
ollama pull qwen3:32b

# 2. Deps:
pip install -r requirements.txt
```

## Run

```bash
# Default: 6 cross-examination rounds, three reasoning models, hybrid history
python main.py "Should a startup with 50k DAU build auth in-house or use Auth0?"

# Shallower / faster, or one model for all roles
python main.py --rounds 3 "..."
python main.py --rounds 2 --single-model qwen3:32b "..."

# A/B the history decision
python main.py --history full "..."     # full record every round
python main.py --history last "..."     # opponent's last turn only

# Machine-readable opinion
python main.py --json "..."
```

Per-role overrides: `--defence-model`, `--prosecution-model`, `--judge-model`.

## Evaluate

```bash
python eval/run_eval.py            # all questions → eval_runs/
python eval/run_eval.py --only 1   # just the Auth0 question
```

Score the outputs by hand against [`eval/criteria.md`](eval/criteria.md). Debate
quality is subjective; the rubric defines it before you run.

## Test

```bash
python -m pytest            # runs the whole proceeding against a FakeLLM, no models
```

## Layout

```
main.py                CLI entry
src/debate/
  config.py            per-role models + reliability tunables
  schemas.py           Pydantic wire schemas + LangGraph DebateState (court record)
  llm.py               Ollama wrapper: json/think/timeout/validation-retry
  prompts.py           framing + advocate contract + per-phase builders + judge
  agents.py            opening / examination / closing / judge nodes (DI for tests)
  graph.py             StateGraph wiring + examination routing
  runner.py            run_debate(), framing, preflight, trace, advisory opinion
eval/                  question battery, harness, manual rubric
tests/                 schemas / parsing / graph (FakeLLM)
docs/                  DESIGN.md, TECHNICAL_DEEP_DIVE.md
```

## Notes

- On the 48 GB reference GPU the 32B judge stays resident and the two ~13 GB
  counsel alternate (the three + KV cache slightly exceed VRAM at 16k context), so
  only the counsel reload per turn. On a small GPU everything swaps — slower but
  fine for a batch proceeding; `--single-model` avoids swaps entirely.
- Reasoning models think before answering, and that hidden trace counts against
  `num_predict` — hence the large per-call token budgets in `config.py`. A budget
  too small truncates the model mid-thought and leaves no room for the JSON answer.
- Every agent output is grammar-constrained (`format=<schema>`) and Pydantic-
  validated; failures degrade to a labelled partial rather than crashing — the
  proceeding always reaches an opinion.
- The opinion is **advisory**: a strong recommendation with grounds and the
  conditions under which the alternative is better, not a binding ruling. You decide.

refer f9r models - https://www.siliconflow.com/articles/en/best-open-source-LLMs-for-reasoning
