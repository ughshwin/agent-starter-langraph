# Session Summary — 2026-06-12

A full export of the working session: what was asked, every decision made and why,
what was built, what is verified versus assumed, and what remains. Two distinct pieces
of work happened this session — a `/doctor` config fix, then the Agentic Pipeline
Inspector build.

---

## Part 1 — `/doctor` settings fix

**Problem reported:** Claude Code's `/doctor` flagged an invalid permission rule in
`C:\Users\ashwi\.claude\settings.json`:

> Invalid permission rule `"mcp__claude-flow__:*"` was skipped: wildcard tool name not
> supported in allow rules.

**Cause:** the rule had a stray colon. Allow rules permit a glob only in the tool
position after a literal `mcp__<server>__` prefix — `mcp__claude-flow__:*` is malformed.

**Fix applied:** changed line 13 to `mcp__claude-flow__*` (allows all tools from the
`claude-flow` MCP server). One-line edit to global settings, confirmed with the user
before writing.

---

## Part 2 — Agentic Pipeline Inspector (spec C1)

### What was asked
Implement a "production-ready agentic pipeline inspector" (item C1 in `Agent List.md`)
in a clean, production-grade repo, learning patterns from the already-complete sibling
projects in this repo. Intended deployment target (stated later): an **A40 GPU VM**
(48 GB VRAM, Linux). Emphasis, in the user's words: *"completeness and capability
soundness over anything and everything."*

### What it is
An autonomous CLI agent that takes a software repository and audits it across five
dimensions of production readiness, producing a prioritised remediation report. The
agent decides what to investigate and how deeply, runs the appropriate scanners, and
synthesises findings — without human guidance during execution.

The hard rule the user reinforced twice: **every finding must come from a dedicated
analysis tool. The LLM only invokes tools and summarises their output — it never runs
analysis itself, and there are no hand-rolled heuristic "rules" standing in for a tool.**
Where no tool covers a check, the report says "not assessed" rather than guessing.

---

## How the work proceeded (process narrative)

1. **Studied the repo's existing complete projects** to match conventions — chiefly
   `multi-agent-debate-system/src/debate/`, which establishes the house style: a
   LangGraph `StateGraph` with a `TypedDict` state using `add` reducers, Pydantic
   schemas constrained by Ollama's `format=<json-schema>`, an `LLMClient` Protocol with
   a real `OllamaLLM` and a `FakeLLM` for tests, a frozen `Settings` dataclass, and
   `tests/` + `docs/` + `eval/` folders.

2. **Brainstormed** the design (superpowers brainstorming skill), surfacing decisions
   and checking the environment.

3. **Wrote and committed a design spec**, then a **detailed TDD implementation plan**.

4. **Course-corrected on process.** The user pushed back hard on ceremony — too much
   documentation and too-frequent commits, not enough functional code. I dropped the
   subagent-driven multi-stage-review workflow and the per-task commits and wrote the
   core agent directly. (This preference is now saved to memory as `workflow-no-ceremony`.)

5. **Built the whole agent**, verified it runs end-to-end against a real repo, then
   installed the pip-based scanners and confirmed it produces **real, accurate,
   prioritised findings**.

6. **Path fix + tests + one commit** (user-requested): normalised finding locations to
   repo-relative paths; wrote 16 FakeLLM-based test files; squashed into one commit.

7. **Capability hardening + deployment completeness** (this final phase) — described in
   detail below.

---

## Key decisions and resolutions

| Topic | Decision | Why |
|-------|----------|-----|
| Orchestration | **LangGraph state machine** (not a raw ReAct loop) | Matches repo conventions; keeps findings deterministic and traceable; gives the LLM agency only where it adds value (triage depth + summary). |
| LLM role | **Invoke + summarise only.** All finding data from tools. No heuristic finding rules. | User's explicit, twice-stated constraint. Keeps the audit trustworthy. |
| Prioritisation | **Computed in code**, LLM only narrates | Deterministic, reproducible ordering; spec Decision 4. |
| Code-quality tool | **SonarQube** (Docker server + `sonar-scanner` + web API) | User chose it explicitly over lighter CLIs. |
| Container tool | **Trivy** | User confirmed (the "cyberflows" they first named was unrecognised; clarified to Trivy). |
| Operational tool | **ruff + dotenv-linter** (named linters); graceful-shutdown / health-check → "not assessed" | No off-the-shelf scanner covers operational readiness; honesty over fabrication. |
| Tool failures | **Assumed installed, but runtime failures degrade** | A timeout / crash / missing binary / unreachable Sonar is noted and skipped; the inspection never aborts (spec Decision 3). |
| Default model | **`qwen2.5:3b`** (override via `--model`) | Fits a 4 GB GPU; the LLM's job here is light. On the A40, `qwen2.5:7b`+ gives better summaries. |
| Sequential vs parallel | **Sequential** dimensions | Simpler; the reducer-backed state allows parallel later with no rearchitect (spec Decision 1). |

---

## Architecture

LangGraph pipeline:

```
START → triage → security → code_quality → container → dependencies → operational → synthesise → END
```

- **triage** — deterministic signal detection (language, Dockerfile, coverage, `.env`),
  then the LLM returns a per-dimension `deep | standard | skip` plan. Control only; no
  findings. Falls back to "standard everywhere" if the LLM errors. Auto-skips
  `container` when there's no Dockerfile.
- **dimension nodes** — each runs its scanners (honouring a `skip` plan), parses their
  structured output into `Finding` objects, and appends to state.
- **synthesise** — normalises finding locations to repo-relative; computes the
  prioritised remediation plan in code; the LLM writes a ≤3-sentence executive summary
  over the findings (with a deterministic fallback if the LLM is down); renders the
  `Report`.

State (`InspectionState`, a `TypedDict`): `findings`, `tools_run`, and `not_assessed`
use `operator.add` reducers, so each node returns only its slice and the graph
accumulates the whole audit.

### The five dimensions and their tools

| Dimension | Tools (all findings come from these) |
|-----------|--------------------------------------|
| Security | semgrep, detect-secrets, bandit |
| Code quality | SonarQube (server + sonar-scanner, read via web API) |
| Container/infra | Trivy (vuln + misconfig + secret) |
| Dependencies | pip-audit (Python), npm audit (JavaScript) |
| Operational | ruff, dotenv-linter |

### Reliability backbone
`tools/base.run_cli()` runs every scanner as a subprocess and **never raises** — on a
missing binary, timeout, or crash it returns a failed result that becomes a
`ToolExecution(success=False, error=...)` noted in the report. The inspection continues.

### Observability
`observability.RunLogger` emits one structured JSON line per tool execution and per LLM
decision (with `--verbose`, also to stderr; always to `inspector_run.jsonl`), so any
report can be traced back to exactly what was run and decided.

---

## Files (46 tracked under `agentic-pipeline-inspector/`)

**Source (`src/inspector/`):** `schemas.py`, `config.py`, `llm.py`, `observability.py`,
`triage.py`, `prioritize.py`, `nodes.py`, `graph.py`, `report.py`, and
`tools/{base,security,code_quality,container,dependencies,operational}.py`.

**Entry point:** `main.py` — CLI: `python main.py inspect <repo> [--format json|md]
[--model M] [--out F] [--verbose]`.

**Tests (`tests/`):** 16 files, **49 passing** in ~1.7 s, using a `FakeLLM` + stubbed
scanner output (need no scanners and no Ollama). Cover every parser, `run_cli`
degradation paths, triage, prioritisation, nodes, report rendering, the CLI, and a full
graph end-to-end run.

**Deployment:** `setup.sh` (installs all scanners on Linux), `docker-compose.sonar.yml`
(Sonar server), `requirements.txt`, `.gitattributes` (LF endings so `setup.sh` runs on
Linux), `.gitignore`.

**Eval:** `eval/run_eval.py` + `eval/repos.md` — drives the real agent against the three
reference repos that define the success criteria.

**Docs:** `README.md`, the design spec, and the implementation plan under
`docs/superpowers/`.

---

## Capability-soundness hardening (final phase)

These fix correctness on real repos, not just "tool is wired":

- **Vendor/build/VCS exclusion** (`node_modules`, `.venv`, `.git`, `dist`, `build`,
  caches, …) applied to **every** scanner — bandit `-x`, semgrep `--exclude`,
  detect-secrets `--exclude-files`, trivy `--skip-dirs` — and to the triage walk. Without
  this, scanners drown in dependency-code noise and a vendored frontend can flip language
  detection. This was the single biggest soundness fix.
- **semgrep** — `scan` subcommand, `--metrics=off`, configurable ruleset (`Settings.semgrep_config`, default `auto`).
- **trivy** — now parses `Secrets` results (the secret scanner output was being dropped).
- **pip-audit** — tolerates the bare-list JSON form (previously crashed the parser).
- **npm audit** — detects a missing lockfile; opt-in in-place lockfile generation
  (`Settings.npm_generate_lockfile`, off by default since it writes to the repo).
- **SonarQube** — polls the compute-engine task to completion before reading issues
  (Sonar processes analysis asynchronously; querying immediately returns stale/empty
  data), and degrades cleanly on scanner or API failure.

---

## Verification status — what's proven vs assumed

**Verified locally (Windows, this machine):**
- Full pipeline runs end-to-end, exit 0, report rendered.
- Graceful degradation: with no scanners installed, every tool reported a noted skip and
  the run still produced a report — no crash.
- With pip scanners installed (bandit, detect-secrets, ruff, pip-audit), the agent
  produced **real, accurate, prioritised findings** on the `cli-research-agent` repo:
  bandit flagged a `urllib` open (B310), ruff flagged two import-order issues (E402),
  ranked by the risk formula, summarised correctly by `qwen2.5:3b`.
- Location normalisation produces repo-relative paths (`main.py:25`, `tools.py:62`).
- 49 unit tests pass.

**NOT verified — assumed correct, unrun here (suspicions / risks):**
- **semgrep** — not installed on Windows (no native Windows support). The command is
  built to current semgrep syntax but its live output on Linux is unconfirmed.
- **Trivy** — not installed locally. Command and JSON parsing (vuln/misconfig/secret)
  are written to Trivy's documented schema but unrun.
- **SonarQube** — no server/Docker locally. The scanner-trigger → CE-poll → issue-read
  flow is implemented to Sonar's documented API but end-to-end behaviour is unconfirmed.
  Suspected rough edges: project auto-provisioning, token/permission scope, and the
  exact `report-task.txt` path under some scanner configs.
- **npm audit** — npm is present but the lockfile-handling path wasn't exercised against
  a real JS repo.
- The **eval harness** imports cleanly but hasn't been run against the three reference
  repos (needs the full toolchain + Ollama).

> Honest note on the commit message for the hardening commit: it says "51 unit tests" —
> the actual count is **49**. The code is correct; the message overcounted by two.

---

## What I hope / expect on the A40 VM

- On Linux with `setup.sh`, **all five dimensions light up** — semgrep and Trivy run
  natively, and the Sonar server stands up via Docker.
- A larger model (`qwen2.5:7b` or bigger, easily within 48 GB) should noticeably improve
  the executive summaries and triage depth choices; the default stays `qwen2.5:3b` for
  portability.
- The vendor-exclusion work should keep scans fast and reports clean even on large repos.
- The three-repo eval should satisfy the spec's success criterion (a senior/staff
  engineer finding the reports accurate and actionable) — though this is the part most
  in need of real human review, and the SonarQube path is the likeliest to need a
  config tweak on first run.

---

## Open items / next steps

1. **Stand up and verify semgrep, Trivy, and SonarQube** on the A40 (or locally) — the
   main unverified surface.
2. **Run `eval/run_eval.py`** against the three reference repos and have a human read the
   reports.
3. Decide whether to **merge** `feat/agentic-pipeline-inspector` into `main`.
4. Optional: gate Python-only tools (bandit, pip-audit) off for JS repos to reduce
   benign "skipped" noise; add pylint/eslint if deeper coverage is wanted.

---

## Git state

- **Branch:** `feat/agentic-pipeline-inspector` (not merged to `main`).
- **Commits this session (newest first):**
  - `1119d51` chore(inspector): force LF line endings for Linux deployment
  - `de26809` feat(inspector): capability hardening + Linux/A40 deployment completeness
  - `7809f38` feat(inspector): agentic pipeline inspector — working agent + tests
  - `9d12c94` docs(inspector): add TDD implementation plan
  - `58526b8` docs(inspector): add approved design spec
- Generated artifacts (`inspector_run.jsonl`, `ruvector.db`) are gitignored.
- The `/doctor` fix to `~/.claude/settings.json` is outside this repo (global config).
