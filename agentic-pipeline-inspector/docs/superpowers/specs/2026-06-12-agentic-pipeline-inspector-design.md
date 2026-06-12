# Agentic Pipeline Inspector — Design

**Date:** 2026-06-12
**Status:** Approved (architecture); pending spec review
**Spec ID:** C1 (see `../../../Agent List.md`)

## 1. Purpose

An autonomous agent that takes a software repository as input, investigates it
across five dimensions of production readiness, and produces a prioritised
remediation report with specific, actionable recommendations. The agent decides
*what to investigate and how deeply*, runs the appropriate scanners, and
synthesises the findings into structured output — without human guidance during
execution.

The report is the product. A senior engineer should read it in five minutes and
know exactly what to fix first and why.

## 2. Scope

### In scope
- Five investigation dimensions: Security, Code Quality, Container/Infrastructure,
  Dependency Health, Operational Readiness.
- Python and JavaScript repositories.
- CLI invocation, JSON **and** markdown report output.
- Full production treatment: `src/` package, FakeLLM unit tests, `DESIGN.md` +
  `TECHNICAL_DEEP_DIVE.md`, eval harness against 3 reference repos.

### Out of scope (non-goals)
- No auto-remediation — identify and recommend only.
- No real-time / continuous monitoring — point-in-time audit.
- No UI.
- No languages beyond Python and JavaScript in v1.

## 3. Key decisions (resolved)

| # | Decision | Resolution |
|---|----------|------------|
| Orchestration | ReAct loop vs LangGraph state machine | **LangGraph state machine** (Approach A). Sequential dimensions; state designed so parallel is a v2 change with no rearchitecting (spec Decision 1). |
| LLM role | How much the model does | **Invoke + summarise only.** LLM selects which tools/depth to invoke (Decision 2 — control, never data) and narrates the prioritised plan + executive summary (Decision 5). **Every finding — flag, severity, location, description — comes from a dedicated analysis tool.** The LLM never runs analysis, and there are **no hand-rolled heuristic finding rules** standing in for a tool. If no tool covers a check, it is reported "not assessed," not evaluated. |
| Prioritisation | LLM vs code | **Computed in code** (deterministic, reproducible) over tool-produced findings only. LLM narrates the ordering but does not compute it (Decision 4). |
| Default model | which Ollama model | **`qwen2.5:3b`** (1.9 GB, fits the 4 GB GPU fully). Config-overridable to `qwen2.5:7b`, `qwen3:8b`, `llama3.1`. |
| Tool availability | required vs graceful | Scanners **assumed installed** (no missing-tool fallback branches in normal operation), but **runtime failures degrade gracefully**: a timeout, crash, unsupported language, or even a missing binary yields a noted `ToolExecution(success=False)` and the inspection continues. One flaky scan never aborts the audit (spec Decision 3). |
| Container dimension | include vs drop | **Included.** `trivy` installed via `winget`/`choco`. |

## 4. Environment (verified 2026-06-12)

- Python 3.14.3, node 24.14, npm 11.11 — present.
- `langgraph` 1.2.4, `pydantic` 2.12.5, `ollama` 0.6.1 — present.
- Ollama models present: `qwen2.5:3b`, `qwen2.5:7b`, `qwen3:8b`, `llama3.1`.
- Scanners **not yet installed**: `semgrep`, `detect-secrets`, `bandit`,
  `pip-audit`, `ruff`/`pylint`, `dotenv-linter`, `trivy`, plus **SonarQube**
  (Docker server + `sonar-scanner` CLI). Installed during setup (see §10).
- `winget` and `choco` available for the `trivy` binary install. Docker required
  for the SonarQube server.

## 5. Architecture (Approach A)

LangGraph `StateGraph` mirroring the existing `multi-agent-debate-system`
conventions (TypedDict state with reducers, Pydantic grammar-constrained LLM
output, `LLMClient` Protocol with a `FakeLLM` for tests).

```
START
  → triage            (detect language + cheap signals; LLM calibrates depth)
  → security          ┐
  → code_quality      │  five dimension nodes, sequential.
  → container         │  each runs its scanners deterministically,
  → dependencies      │  parses stdout → list[Finding], appends to state.
  → operational       ┘
  → synthesise        (code computes prioritised plan; LLM writes summary + narration)
  → END
```

`triage` is the only node whose *control* output the LLM influences (the
per-dimension depth plan). Every dimension node's *data* output is pure tool
parsing. `synthesise` reads accumulated findings; prioritisation is computed in
code, the LLM narrates.

## 6. Package layout

```
agentic-pipeline-inspector/
  src/inspector/
    __init__.py
    schemas.py        # Pydantic wire schemas + InspectionState TypedDict + enums
    config.py         # frozen Settings: model, timeouts, per-dimension tool map
    llm.py            # LLMClient Protocol, OllamaLLM (format=<json-schema>)
    observability.py  # structured JSON run logging (Decision 6)
    tools/
      __init__.py
      base.py         # ToolResult, run_cli() — timeout, capture, never raises
      security.py     # semgrep, detect-secrets, bandit → Finding
      code_quality.py # SonarQube: trigger sonar-scanner, read issues via Sonar web API → Finding
      container.py    # trivy (Dockerfile / image / compose) → Finding
      dependencies.py # pip-audit (py), npm audit (js) → Finding
      operational.py  # bandit, ruff/pylint, dotenv-linter (named-tool rules only) → Finding
    triage.py         # repo signal detection + LLM depth calibration node
    nodes.py          # the five dimension nodes + synthesise node
    prioritize.py     # deterministic risk-adjusted ordering
    report.py         # Report assembly + JSON / markdown renderers
    graph.py          # LangGraph wiring
  main.py             # CLI entry
  tests/
    conftest.py       # FakeLLM + fixture repos
    fixtures/         # captured scanner outputs + tiny sample repos
    test_*.py
  docs/
    DESIGN.md
    TECHNICAL_DEEP_DIVE.md
    superpowers/specs/2026-06-12-agentic-pipeline-inspector-design.md  (this file)
  eval/
    run_eval.py       # runs full inspection vs 3 reference repos
    repos.md          # the 3 reference targets + expected signal
  requirements.txt
  README.md
```

## 7. Data model

```python
class Dimension(str, Enum):
    SECURITY = "security"
    CODE_QUALITY = "code_quality"
    CONTAINER = "container"
    DEPENDENCIES = "dependencies"
    OPERATIONAL = "operational"

class Severity(str, Enum):  # ordered for sorting
    CRITICAL = "critical"; HIGH = "high"; MEDIUM = "medium"; LOW = "low"

class Finding(BaseModel):
    dimension: Dimension
    severity: Severity
    location: str            # "file:line" — from the tool, never the LLM
    description: str         # from the tool
    recommendation: str      # from the tool's own remediation text where provided
    effort_hours: float      # from the tool where it reports effort (SonarQube debt);
                             # else a fixed severity→hours lookup in config (a constant
                             # table, not repo analysis — see §8)
    tool: str                # which scanner produced it (provenance)
    rule_id: str | None      # CVE / rule reference where available

class ToolExecution(BaseModel):
    tool_name: str
    input: dict
    success: bool
    duration_ms: int
    error: str | None        # populated when success is False (Decision 3)

class RemediationStep(BaseModel):
    rank: int
    finding: Finding
    risk_score: float
    rationale: str           # why this rank (code-generated facts; LLM may narrate)

class Report(BaseModel):
    executive_summary: str           # LLM, <= 3 sentences
    repo_path: str
    repo_language: str
    critical_count: int
    findings_by_severity: dict[Severity, int]
    prioritised_remediation_plan: list[RemediationStep]
    estimated_total_effort_hours: float
    skipped: list[ToolExecution]     # tools that failed/were unsupported

class InspectionState(TypedDict):
    repo_path: str
    repo_language: str
    depth_plan: dict[Dimension, str]              # LLM triage output: deep|standard|skip
    findings: Annotated[list[Finding], add]       # reducer-accumulated
    tools_run: Annotated[list[ToolExecution], add]
    report: Optional[Report]
```

## 8. Tool wrappers

Each scanner has one parser function: `run() -> tuple[list[Finding], ToolExecution]`.
`base.run_cli(cmd, timeout)` runs a subprocess, captures stdout/stderr, enforces
the timeout, and **never raises** — it returns a `ToolResult(ok, stdout, stderr,
duration_ms, error)`. Parsers map **structured tool output** (JSON where the tool
supports it — semgrep `--json`, pip-audit `--format json`, npm audit `--json`,
trivy `--format json`, the SonarQube web API, bandit `-f json`, ruff `--output-format
json`) into `Finding` objects. **No parser invents data**: it only reshapes what the
tool reported.

| Dimension | Tools (all findings come from these) | Output → Finding |
|-----------|--------------------------------------|------------------|
| Security | semgrep (`--json`), detect-secrets, bandit (`-f json`) | dangerous patterns, hardcoded secrets |
| Code Quality | **SonarQube** (Community server in Docker; `sonar-scanner` runs the analysis, agent reads issues + technical-debt effort via the Sonar web API) | complexity, duplication, code smells, bugs, coverage |
| Container | trivy (`--format json`) | base-image CVEs, Dockerfile/IaC misconfig |
| Dependencies | pip-audit (py), npm audit (js) | vulnerable deps + CVE refs |
| Operational | bandit (error handling / dangerous calls), ruff or pylint (broad lint incl. logging, bare-except, dead code), dotenv-linter (config) | weak error handling, logging gaps, config issues |

> **Operational coverage limits, stated honestly.** No tool detects
> graceful-shutdown handlers or container health-checks directly. Those sub-checks
> are reported as **"not assessed"** in the report — never evaluated by a heuristic.
> The report only asserts what a named tool actually found. SonarQube findings are
> tagged to the Code Quality dimension; the operational linters above are distinct.

## 9. Triage, prioritisation, observability

**Triage (Decision 2):** detect `repo_language` (file extensions / manifest
files), whether a `Dockerfile`/`compose` exists, dependency count, existing
coverage report. Feed these signals to the LLM, which returns a `depth_plan`:
`deep | standard | skip` per dimension (e.g. skip `container` when no Dockerfile;
`deep` code-quality when coverage is absent). Control-only — never fabricates data.

**Prioritisation (Decision 4):** `risk_score = severity_weight × path_criticality ÷
max(effort_hours, 0.5)`. `path_criticality` boosts findings in auth / entrypoint /
config / network-exposed files. Findings sharing a `rule_id` or root cause are
grouped. Sorted highest-risk-lowest-effort first. Pure code.

**Observability (Decision 6):** `observability.py` emits one structured JSON log
line per tool execution (name, input, duration_ms, success, error) and per LLM
decision (triage depth plan + the signals that drove it). Written to a per-run log
so any report can be traced back to exactly what was investigated and concluded.

## 10. Setup / installation

```
# Python scanners (+ langgraph pydantic ollama)
pip install semgrep detect-secrets bandit pip-audit ruff pylint

# Container scanner (binary)
winget install AquaSecurity.Trivy           # or: choco install trivy

# Config linter (binary)
winget install dotenv-linter.dotenv-linter  # or download release binary

# SonarQube Community server (Docker) + scanner CLI
docker run -d --name sonarqube -p 9000:9000 sonarqube:community
#   then create a project token in the Sonar UI; sonar-scanner CLI installed separately
ollama pull qwen2.5:3b                       # already present
```

Python tools pinned in `requirements.txt`. `trivy`, `dotenv-linter`, `sonar-scanner`,
and the SonarQube Docker server are documented in the README (not pip). The Sonar
server URL + token are read from config/env.

## 11. Error handling

- `run_cli` never raises; failures become `ToolExecution(success=False, error=...)`.
- Per-tool timeout from `Settings`.
- Unsupported language for a tool → noted skip, continue.
- **SonarQube server unreachable** (Docker not running / bad token) → Code Quality
  dimension noted as failed in the report, inspection continues. Never aborts.
- LLM call failures in `triage`/`synthesise`: triage falls back to `standard`
  depth for all dimensions; synthesise falls back to a code-generated summary.
  The audit data (findings) is unaffected because it comes from tools.

## 12. Testing

- `FakeLLM` injected via `conftest` → full graph runs with no model (deterministic).
- Each tool parser unit-tested against captured real scanner output fixtures.
- `run_cli` timeout/failure paths tested with fake subprocesses.
- Prioritisation tested on synthetic finding sets (ordering is pure function).
- Graph smoke test on a tiny fixture repo.

## 13. Success criteria

Run against three repos: a well-maintained OSS project, an intentionally
vulnerable project (e.g. DVWA), and the user's own project. The vulnerable
project's report surfaces all critical security issues; the well-maintained one
yields a short low-severity list; the user's gives genuinely actionable feedback.
A senior/staff engineer reviewing all three calls them accurate and actionable.

## 14. CLI

```
python main.py inspect <repo_path> [--format json|md] [--model qwen2.5:3b] [--out report.md] [--verbose]
```
Default: markdown to stdout. `--format json` for machine consumption.
```
