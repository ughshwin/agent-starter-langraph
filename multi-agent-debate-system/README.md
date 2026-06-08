# Multi-Agent Debate System

Three local LLM agents debate a technical decision and produce a structured,
nuanced verdict. A **Proposer** argues *for*, an **Opposer** argues *against*, and
a **Judge** steers each round and synthesises a final recommendation with explicit
conditions and dissent. Built on **LangGraph** with **local Ollama models only** —
no API keys, no cloud, no tools.

> Adversarial coordination, persistent conflicting objectives, multi-round state,
> and synthesis from conflicting inputs. See [`docs/DESIGN.md`](docs/DESIGN.md) and
> [`docs/TECHNICAL_DEEP_DIVE.md`](docs/TECHNICAL_DEEP_DIVE.md).

## How it works

```
START → proposer → opposer → judge_observe → [route]
                                                ├─ more rounds → proposer (loop)
                                                └─ last round  → judge_verdict → END
```

Each round: Proposer argues → Opposer rebuts → Judge observes what's missing and
steers the next round. After the final round (2 or 3) the Judge produces a
`Verdict { recommendation, confidence, key_factors, conditions, dissenting_considerations }`.

## Three models, one per role

| Role | Default | Why |
|------|---------|-----|
| Proposer | `llama3.1:latest` | assertive advocate |
| Opposer | `qwen2.5:7b` | different model family → genuine disagreement, not an echo |
| Judge | `qwen3:8b` (thinking) | the only reasoning model → deep synthesis |

Heterogeneous families are a deliberate defence against the failure mode where two
identical helpful models converge on the same answer.

## Setup

```bash
# 1. Ollama running, with the three models pulled:
ollama pull llama3.1
ollama pull qwen2.5:7b
ollama pull qwen3:8b

# 2. Deps:
pip install -r requirements.txt
```

## Run

```bash
# Default: 3 rounds, three models, hybrid history, live trace
python main.py "Should a startup with 50k DAU build auth in-house or use Auth0?"

# Faster: 2 rounds, one model for all roles
python main.py --rounds 2 --single-model qwen3:8b "..."

# A/B the brief's history decision
python main.py --history full "..."     # full transcript every round
python main.py --history last "..."     # opponent's last argument only

# Machine-readable verdict
python main.py --json "..."
```

Per-role overrides: `--proposer-model`, `--opposer-model`, `--judge-model`.

## Evaluate

```bash
python eval/run_eval.py            # all questions → eval_runs/
python eval/run_eval.py --only 1   # just the Auth0 question
```

Score the outputs by hand against [`eval/criteria.md`](eval/criteria.md). Debate
quality is subjective; the rubric defines it before you run.

## Test

```bash
python -m pytest            # runs the whole graph against a FakeLLM, no models needed
```

## Layout

```
main.py                CLI entry
src/debate/
  config.py            per-role models + reliability tunables
  schemas.py           Pydantic models + LangGraph DebateState
  llm.py               Ollama wrapper: json/think/timeout/validation-retry
  prompts.py           role-commitment prompts + history-mode builders
  agents.py            proposer / opposer / judge nodes (client injected for tests)
  graph.py             StateGraph wiring + routing
  runner.py            run_debate(), preflight, trace, degradation
eval/                  question battery, harness, manual rubric
tests/                 schemas / parsing / graph (FakeLLM)
docs/                  DESIGN.md, TECHNICAL_DEEP_DIVE.md
```

## Notes

- On a 4 GB GPU only one ~8B model is resident at a time, so Ollama swaps models
  per turn (a few seconds each). Fine for a non-real-time batch debate;
  `--single-model` avoids swaps.
- Every agent output is grammar-constrained (`format=<schema>`) and Pydantic-
  validated; failures degrade to a labelled partial rather than crashing.
