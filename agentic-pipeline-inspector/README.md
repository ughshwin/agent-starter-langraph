# Agentic Pipeline Inspector

A point-in-time **production-readiness auditor** for Python and JavaScript repos.
Give it a repo path; it investigates five dimensions with dedicated analysis tools,
reasons about *what* to investigate and *how deeply*, and produces a prioritised
remediation report. **Every finding comes from a real analysis tool** — the LLM only
decides investigation depth and writes the summary; it never invents findings.

## How it works

LangGraph pipeline:

```
triage → security → code_quality → container → dependencies → operational → synthesise
```

- **triage** — detects language + cheap signals (Dockerfile? coverage?), then the LLM
  picks `deep | standard | skip` per dimension. Control only — no findings here.
- **dimension nodes** — each runs its scanners and parses their output into `Finding`s.
- **synthesise** — prioritisation is computed in code (deterministic), the LLM writes a
  ≤3-sentence executive summary over the tool findings.

| Dimension | Tools |
|-----------|-------|
| Security | semgrep, detect-secrets, bandit |
| Code quality | SonarQube (server + sonar-scanner, read via web API) |
| Container/infra | trivy |
| Dependencies | pip-audit (Python), npm audit (JavaScript) |
| Operational | ruff, dotenv-linter |

Checks no tool covers (graceful-shutdown handlers, container health-checks) are
reported as **"not assessed"**, never guessed.

**Reliability:** every tool runs through a subprocess wrapper that never raises. A
missing binary, timeout, crash, unsupported language, or unreachable SonarQube server
degrades to a noted skip and the inspection continues — one flaky scan never aborts the
audit.

## Setup (Linux / A40 VM)

```bash
# 1. Python deps + all CLI scanners (semgrep, detect-secrets, bandit, pip-audit, ruff,
#    trivy, dotenv-linter, sonar-scanner)
./setup.sh

# 2. SonarQube server (for the code-quality dimension)
docker compose -f docker-compose.sonar.yml up -d
#    open http://localhost:9000 (admin/admin), create a token, then:
export SONAR_URL=http://localhost:9000
export SONAR_TOKEN=<token>
export SONAR_PROJECT_KEY=inspector-target

# 3. Ollama model (setup.sh pulls qwen2.5:3b; on a 48GB A40 a larger model gives
#    better summaries)
ollama pull qwen2.5:7b
```

## Usage

```bash
python main.py inspect <repo_path> [--format json|md] [--model M] [--out FILE] [--verbose]
```

- `--format md` (default) → human report to stdout; `--format json` → machine-readable.
- `--model qwen2.5:7b` → override the LLM (default `qwen2.5:3b`).
- `--out report.md` → write to a file instead of stdout.
- `--verbose` → stream structured run logs (every tool + decision) to stderr; also
  written to `inspector_run.jsonl` for full traceability.

Example:

```bash
python main.py inspect /path/to/repo --model qwen2.5:7b --out report.md --verbose
```

## Evaluation

Validate against the three reference repos from the spec:

```bash
python eval/run_eval.py /tmp/eval/click /tmp/eval/nodegoat /path/to/your/repo
```

See `eval/repos.md`.

## Tests

```bash
python -m pytest -q
```

Unit tests use a `FakeLLM` and stubbed scanner output — they need **no scanners and no
Ollama** and run in ~2s. They cover every tool parser, the never-raising subprocess
runner, triage, prioritisation, report rendering, the CLI, and a full graph run.

## Known limitations (v1)

- **semgrep** has no native Windows support; on Linux it runs normally. The agent
  degrades gracefully where any tool is absent.
- **npm audit** requires a lockfile. If a JS repo has none, set
  `npm_generate_lockfile=True` in `Settings` to generate one in place before auditing
  (writes to the repo — off by default).
- **SonarQube** analysis is processed asynchronously; the agent polls the compute-engine
  task to completion before reading issues, so a slow first analysis costs time, not
  correctness.
- Python and JavaScript only.

Design and rationale: `docs/superpowers/specs/2026-06-12-agentic-pipeline-inspector-design.md`.
