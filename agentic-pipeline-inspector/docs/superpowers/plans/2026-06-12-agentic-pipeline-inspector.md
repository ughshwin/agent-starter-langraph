# Agentic Pipeline Inspector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI agent that audits a Python/JavaScript repo across five production-readiness dimensions and emits a prioritised remediation report — where every finding comes from a dedicated analysis tool and the LLM only orchestrates and summarises.

**Architecture:** LangGraph `StateGraph` (Approach A): `triage → security → code_quality → container → dependencies → operational → synthesise → END`. Findings accumulate in a reducer-backed `InspectionState`. Tool wrappers shell out via a never-raising `run_cli` and parse structured tool output into `Finding` objects. The LLM (default `qwen2.5:3b` via Ollama) is used only in `triage` (pick tool depth) and `synthesise` (executive summary). Prioritisation is pure deterministic code.

**Tech Stack:** Python 3.14, LangGraph 1.2, Pydantic 2.12, Ollama 0.6, pytest 9. Scanners: semgrep, detect-secrets, bandit, pip-audit, npm audit, trivy, SonarQube (Docker + web API), ruff, dotenv-linter.

**Reference:** Mirror conventions from `../../../multi-agent-debate-system/src/debate/` (LLMClient Protocol + OllamaLLM, FakeLLM in tests, frozen Settings, TypedDict state with `add` reducers, grammar-constrained JSON).

**Working dir for all paths below:** `d:/Work/agent-starter-langraph/agentic-pipeline-inspector/`

---

## Task 0: Project scaffolding

**Files:**
- Create: `requirements.txt`, `README.md`, `src/inspector/__init__.py`, `src/inspector/tools/__init__.py`, `tests/__init__.py`, `pytest.ini`

- [ ] **Step 1: Create `requirements.txt`**

```
langgraph==1.2.4
pydantic==2.12.5
ollama==0.6.1
semgrep
detect-secrets
bandit
pip-audit
ruff
pytest==9.0.2
pytest-cov
requests
```

- [ ] **Step 2: Create `pytest.ini`**

```ini
[pytest]
pythonpath = src .
testpaths = tests
```

- [ ] **Step 3: Create empty package markers**

`src/inspector/__init__.py`, `src/inspector/tools/__init__.py`, `tests/__init__.py` — each empty.

- [ ] **Step 4: Create `README.md` stub**

```markdown
# Agentic Pipeline Inspector

Point-in-time production-readiness auditor for Python/JavaScript repos.
See `docs/superpowers/specs/2026-06-12-agentic-pipeline-inspector-design.md`.

## Setup
See spec §10. Requires: pip deps (`pip install -r requirements.txt`), trivy,
dotenv-linter, a SonarQube Community server (Docker) + sonar-scanner, and Ollama
with `qwen2.5:3b`.

## Usage
    python main.py inspect <repo_path> [--format json|md] [--out report.md]
```

- [ ] **Step 5: Commit**

```bash
git add agentic-pipeline-inspector
git commit -m "chore(inspector): scaffold project structure and deps"
```

---

## Task 1: Schemas and state

**Files:**
- Create: `src/inspector/schemas.py`
- Test: `tests/test_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schemas.py
from inspector.schemas import (
    Dimension, Severity, Finding, ToolExecution, RemediationStep, Report,
    SEVERITY_WEIGHT,
)


def test_severity_is_ordered_by_weight():
    assert SEVERITY_WEIGHT[Severity.CRITICAL] > SEVERITY_WEIGHT[Severity.HIGH]
    assert SEVERITY_WEIGHT[Severity.HIGH] > SEVERITY_WEIGHT[Severity.MEDIUM]
    assert SEVERITY_WEIGHT[Severity.MEDIUM] > SEVERITY_WEIGHT[Severity.LOW]


def test_finding_round_trips():
    f = Finding(
        dimension=Dimension.SECURITY, severity=Severity.HIGH, location="app.py:10",
        description="eval used", recommendation="avoid eval", effort_hours=1.0,
        tool="bandit", rule_id="B307",
    )
    assert Finding.model_validate_json(f.model_dump_json()) == f


def test_report_counts_default_empty():
    r = Report(
        executive_summary="ok", repo_path=".", repo_language="python",
        critical_count=0, findings_by_severity={}, prioritised_remediation_plan=[],
        estimated_total_effort_hours=0.0, skipped=[],
    )
    assert r.critical_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'inspector.schemas'`

- [ ] **Step 3: Write `src/inspector/schemas.py`**

```python
"""Data shapes for an inspection.

Two layers: wire schemas the LLM fills (triage/summary) and the audit data
(`Finding`, `Report`) which comes only from tools. `InspectionState` is the
LangGraph working memory; `findings`/`tools_run` use `add` reducers so each node
returns only its slice and the graph accumulates the whole audit.
"""
from __future__ import annotations

from enum import Enum
from operator import add
from typing import Annotated, Optional, TypedDict

from pydantic import BaseModel, Field


class Dimension(str, Enum):
    SECURITY = "security"
    CODE_QUALITY = "code_quality"
    CONTAINER = "container"
    DEPENDENCIES = "dependencies"
    OPERATIONAL = "operational"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_WEIGHT = {
    Severity.CRITICAL: 8.0,
    Severity.HIGH: 4.0,
    Severity.MEDIUM: 2.0,
    Severity.LOW: 1.0,
}

# Fixed fallback effort estimate (hours) when a tool does not report effort.
# A constant table — NOT repo analysis.
DEFAULT_EFFORT_HOURS = {
    Severity.CRITICAL: 4.0,
    Severity.HIGH: 2.0,
    Severity.MEDIUM: 1.0,
    Severity.LOW: 0.5,
}


class Finding(BaseModel):
    dimension: Dimension
    severity: Severity
    location: str            # "file:line" from the tool
    description: str         # from the tool
    recommendation: str      # from the tool, or "" if none provided
    effort_hours: float
    tool: str                # provenance
    rule_id: Optional[str] = None


class ToolExecution(BaseModel):
    tool_name: str
    input: dict
    success: bool
    duration_ms: int
    error: Optional[str] = None


class RemediationStep(BaseModel):
    rank: int
    finding: Finding
    risk_score: float
    rationale: str


class Report(BaseModel):
    executive_summary: str
    repo_path: str
    repo_language: str
    critical_count: int
    findings_by_severity: dict[Severity, int]
    prioritised_remediation_plan: list[RemediationStep]
    estimated_total_effort_hours: float
    skipped: list[ToolExecution]
    not_assessed: list[str] = Field(default_factory=list)


# --- LLM wire schemas (the ONLY things the model fills) ----------------------

class DepthPlan(BaseModel):
    """Triage output: how deeply to investigate each dimension. Control only."""
    security: str = Field(description="one of: deep | standard | skip")
    code_quality: str = Field(description="one of: deep | standard | skip")
    container: str = Field(description="one of: deep | standard | skip")
    dependencies: str = Field(description="one of: deep | standard | skip")
    operational: str = Field(description="one of: deep | standard | skip")


class ExecutiveSummary(BaseModel):
    """Synthesise output: prose only, over findings the tools produced."""
    summary: str = Field(
        description="At most 3 sentences. What is the overall production-readiness "
        "state and what should be fixed first. Do not invent findings."
    )


class InspectionState(TypedDict):
    repo_path: str
    repo_language: str
    depth_plan: dict[str, str]
    findings: Annotated[list[Finding], add]
    tools_run: Annotated[list[ToolExecution], add]
    not_assessed: Annotated[list[str], add]
    report: Optional[Report]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schemas.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inspector/schemas.py tests/test_schemas.py
git commit -m "feat(inspector): add schemas and inspection state"
```

---

## Task 2: Config

**Files:**
- Create: `src/inspector/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest
from inspector.config import Settings


def test_defaults():
    s = Settings()
    assert s.model == "qwen2.5:3b"
    assert s.tool_timeout > 0
    s.validate()


def test_validate_rejects_bad_timeout():
    with pytest.raises(ValueError):
        Settings(tool_timeout=0).validate()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `src/inspector/config.py`**

```python
"""Settings: model, per-tool timeout, SonarQube connection, reliability tunables."""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL = "qwen2.5:3b"


@dataclass(frozen=True)
class Settings:
    model: str = DEFAULT_MODEL
    tool_timeout: float = 300.0          # seconds per scanner subprocess
    llm_timeout: float = 240.0
    llm_num_predict: int = 700
    validation_retries: int = 2

    # SonarQube (read from env so tokens never live in code)
    sonar_url: str = os.environ.get("SONAR_URL", "http://localhost:9000")
    sonar_token: str = os.environ.get("SONAR_TOKEN", "")
    sonar_project_key: str = os.environ.get("SONAR_PROJECT_KEY", "inspector-target")

    verbose: bool = True

    def validate(self) -> None:
        if self.tool_timeout <= 0:
            raise ValueError(f"tool_timeout must be > 0, got {self.tool_timeout}")
        if self.llm_timeout <= 0:
            raise ValueError(f"llm_timeout must be > 0, got {self.llm_timeout}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inspector/config.py tests/test_config.py
git commit -m "feat(inspector): add settings"
```

---

## Task 3: Tool runner (`run_cli`)

**Files:**
- Create: `src/inspector/tools/base.py`
- Test: `tests/test_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_base.py
import sys
from inspector.tools.base import run_cli, ToolResult


def test_run_cli_captures_stdout():
    r = run_cli([sys.executable, "-c", "print('hi')"], timeout=30)
    assert isinstance(r, ToolResult)
    assert r.ok
    assert "hi" in r.stdout
    assert r.duration_ms >= 0


def test_run_cli_nonzero_exit_is_not_ok_but_does_not_raise():
    r = run_cli([sys.executable, "-c", "import sys; sys.exit(2)"], timeout=30)
    assert r.ok is False
    assert r.returncode == 2


def test_run_cli_missing_binary_returns_error_not_raise():
    r = run_cli(["this_binary_does_not_exist_xyz"], timeout=30)
    assert r.ok is False
    assert r.error is not None


def test_run_cli_timeout_returns_error_not_raise():
    r = run_cli([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)
    assert r.ok is False
    assert "timeout" in (r.error or "").lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_base.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `src/inspector/tools/base.py`**

```python
"""Subprocess runner that NEVER raises. Every tool wrapper goes through this so a
flaky scanner can't abort the inspection (spec Decision 3)."""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ToolResult:
    ok: bool                 # process ran AND exited 0
    returncode: Optional[int]
    stdout: str
    stderr: str
    duration_ms: int
    error: Optional[str] = None   # set when the process could not run / timed out


def run_cli(cmd: list[str], timeout: float, cwd: Optional[str] = None) -> ToolResult:
    """Run `cmd`, capturing output. Returns a ToolResult; never raises.

    Note: a non-zero exit is `ok=False` but `error=None` (the tool ran, it just
    found problems or failed) — many scanners exit non-zero when they find issues,
    so callers that expect that should check stdout regardless of `ok`.
    A failure to launch or a timeout sets `error`.
    """
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
    except FileNotFoundError as exc:
        ms = int((time.monotonic() - start) * 1000)
        return ToolResult(False, None, "", "", ms, error=f"binary not found: {exc}")
    except subprocess.TimeoutExpired:
        ms = int((time.monotonic() - start) * 1000)
        return ToolResult(False, None, "", "", ms, error=f"timeout after {timeout}s")
    except Exception as exc:  # last-resort guard; runner must never raise
        ms = int((time.monotonic() - start) * 1000)
        return ToolResult(False, None, "", "", ms, error=f"{type(exc).__name__}: {exc}")
    ms = int((time.monotonic() - start) * 1000)
    return ToolResult(
        ok=(proc.returncode == 0), returncode=proc.returncode,
        stdout=proc.stdout or "", stderr=proc.stderr or "", duration_ms=ms,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_base.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inspector/tools/base.py tests/test_base.py
git commit -m "feat(inspector): add never-raising subprocess runner"
```

---

## Task 4: Security tools (semgrep, detect-secrets, bandit)

**Files:**
- Create: `src/inspector/tools/security.py`
- Test: `tests/test_security_tools.py`, `tests/fixtures/__init__.py`

Each wrapper signature: `run(repo_path, settings) -> tuple[list[Finding], ToolExecution]`.
Parsing is split into a pure `parse_<tool>(stdout) -> list[Finding]` function so it
can be unit-tested without a subprocess.

- [ ] **Step 1: Write the failing test (pure parsers against captured JSON)**

```python
# tests/test_security_tools.py
import json
from inspector.schemas import Dimension, Severity
from inspector.tools.security import parse_bandit, parse_semgrep, parse_detect_secrets

BANDIT = json.dumps({
    "results": [{
        "filename": "app.py", "line_number": 12, "issue_text": "Use of eval",
        "issue_severity": "HIGH", "test_id": "B307",
    }]
})

SEMGREP = json.dumps({
    "results": [{
        "check_id": "python.lang.security.audit.dangerous-exec",
        "path": "svc.py", "start": {"line": 4},
        "extra": {"message": "exec is dangerous", "severity": "ERROR"},
    }]
})

DETECT_SECRETS = json.dumps({
    "results": {
        "config.py": [{"type": "AWS Access Key", "line_number": 7}]
    }
})


def test_parse_bandit():
    fs = parse_bandit(BANDIT)
    assert len(fs) == 1
    assert fs[0].dimension == Dimension.SECURITY
    assert fs[0].severity == Severity.HIGH
    assert fs[0].location == "app.py:12"
    assert fs[0].rule_id == "B307"
    assert fs[0].tool == "bandit"


def test_parse_semgrep_maps_error_to_high():
    fs = parse_semgrep(SEMGREP)
    assert fs[0].severity == Severity.HIGH
    assert fs[0].location == "svc.py:4"
    assert fs[0].tool == "semgrep"


def test_parse_detect_secrets():
    fs = parse_detect_secrets(DETECT_SECRETS)
    assert fs[0].severity == Severity.CRITICAL
    assert fs[0].location == "config.py:7"
    assert "AWS Access Key" in fs[0].description


def test_parsers_tolerate_empty_or_garbage():
    assert parse_bandit("") == []
    assert parse_semgrep("not json") == []
    assert parse_detect_secrets("{}") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_security_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `src/inspector/tools/security.py`**

```python
"""Security dimension: semgrep, detect-secrets, bandit. Parsers are pure; `run_*`
shell out via run_cli. Findings come ONLY from tool output."""
from __future__ import annotations

import json
from typing import Optional

from ..config import Settings
from ..schemas import DEFAULT_EFFORT_HOURS, Dimension, Finding, Severity, ToolExecution
from .base import run_cli

_SEMGREP_SEVERITY = {"ERROR": Severity.HIGH, "WARNING": Severity.MEDIUM, "INFO": Severity.LOW}
_BANDIT_SEVERITY = {"HIGH": Severity.HIGH, "MEDIUM": Severity.MEDIUM, "LOW": Severity.LOW}


def _loads(stdout: str) -> Optional[dict]:
    try:
        return json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None


def _finding(dimension, severity, location, description, tool, rule_id, recommendation=""):
    return Finding(
        dimension=dimension, severity=severity, location=location,
        description=description, recommendation=recommendation,
        effort_hours=DEFAULT_EFFORT_HOURS[severity], tool=tool, rule_id=rule_id,
    )


def parse_bandit(stdout: str) -> list[Finding]:
    data = _loads(stdout)
    if not data:
        return []
    out = []
    for r in data.get("results", []):
        sev = _BANDIT_SEVERITY.get(r.get("issue_severity", "").upper(), Severity.MEDIUM)
        loc = f"{r.get('filename', '?')}:{r.get('line_number', 0)}"
        out.append(_finding(Dimension.SECURITY, sev, loc, r.get("issue_text", ""),
                            "bandit", r.get("test_id")))
    return out


def parse_semgrep(stdout: str) -> list[Finding]:
    data = _loads(stdout)
    if not data:
        return []
    out = []
    for r in data.get("results", []):
        extra = r.get("extra", {})
        sev = _SEMGREP_SEVERITY.get(extra.get("severity", "").upper(), Severity.MEDIUM)
        loc = f"{r.get('path', '?')}:{r.get('start', {}).get('line', 0)}"
        out.append(_finding(Dimension.SECURITY, sev, loc, extra.get("message", ""),
                            "semgrep", r.get("check_id")))
    return out


def parse_detect_secrets(stdout: str) -> list[Finding]:
    data = _loads(stdout)
    if not data:
        return []
    out = []
    for filename, secrets in (data.get("results") or {}).items():
        for s in secrets:
            loc = f"{filename}:{s.get('line_number', 0)}"
            out.append(_finding(
                Dimension.SECURITY, Severity.CRITICAL, loc,
                f"Potential secret: {s.get('type', 'unknown')}", "detect-secrets",
                None, recommendation="Remove the secret and rotate the credential.",
            ))
    return out


def _exec(tool, inp, result) -> ToolExecution:
    return ToolExecution(
        tool_name=tool, input=inp, success=(result.error is None),
        duration_ms=result.duration_ms, error=result.error,
    )


def run_semgrep(repo_path: str, settings: Settings):
    r = run_cli(["semgrep", "--config", "auto", "--json", repo_path],
                timeout=settings.tool_timeout)
    return parse_semgrep(r.stdout), _exec("semgrep", {"path": repo_path}, r)


def run_detect_secrets(repo_path: str, settings: Settings):
    r = run_cli(["detect-secrets", "scan", repo_path], timeout=settings.tool_timeout)
    return parse_detect_secrets(r.stdout), _exec("detect-secrets", {"path": repo_path}, r)


def run_bandit(repo_path: str, settings: Settings):
    r = run_cli(["bandit", "-r", repo_path, "-f", "json"], timeout=settings.tool_timeout)
    return parse_bandit(r.stdout), _exec("bandit", {"path": repo_path}, r)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_security_tools.py -v`
Expected: PASS (4 passed). Create empty `tests/fixtures/__init__.py` if import errors.

- [ ] **Step 5: Commit**

```bash
git add src/inspector/tools/security.py tests/test_security_tools.py
git commit -m "feat(inspector): add security tool wrappers"
```

---

## Task 5: Dependency tools (pip-audit, npm audit)

**Files:**
- Create: `src/inspector/tools/dependencies.py`
- Test: `tests/test_dependency_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dependency_tools.py
import json
from inspector.schemas import Dimension, Severity
from inspector.tools.dependencies import parse_pip_audit, parse_npm_audit

PIP = json.dumps({
    "dependencies": [{
        "name": "flask", "version": "0.5",
        "vulns": [{"id": "PYSEC-2019-1", "fix_versions": ["1.0"],
                   "description": "XSS in flask"}],
    }]
})

NPM = json.dumps({
    "vulnerabilities": {
        "lodash": {"severity": "high", "via": [{"title": "Prototype pollution",
                   "url": "https://x", "source": 1065}], "range": "<4.17.12"}
    }
})


def test_parse_pip_audit():
    fs = parse_pip_audit(PIP)
    assert fs[0].dimension == Dimension.DEPENDENCIES
    assert fs[0].rule_id == "PYSEC-2019-1"
    assert "flask" in fs[0].location
    assert fs[0].tool == "pip-audit"


def test_parse_npm_audit_maps_high():
    fs = parse_npm_audit(NPM)
    assert fs[0].severity == Severity.HIGH
    assert "lodash" in fs[0].location
    assert fs[0].tool == "npm-audit"


def test_dependency_parsers_tolerate_garbage():
    assert parse_pip_audit("") == []
    assert parse_npm_audit("nope") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dependency_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `src/inspector/tools/dependencies.py`**

```python
"""Dependency health: pip-audit (Python), npm audit (JavaScript)."""
from __future__ import annotations

import json
import os
from typing import Optional

from ..config import Settings
from ..schemas import DEFAULT_EFFORT_HOURS, Dimension, Finding, Severity, ToolExecution
from .base import run_cli

_NPM_SEVERITY = {
    "critical": Severity.CRITICAL, "high": Severity.HIGH,
    "moderate": Severity.MEDIUM, "low": Severity.LOW, "info": Severity.LOW,
}


def _loads(stdout: str) -> Optional[dict]:
    try:
        return json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None


def _finding(dimension, severity, location, description, tool, rule_id, recommendation=""):
    return Finding(
        dimension=dimension, severity=severity, location=location,
        description=description, recommendation=recommendation,
        effort_hours=DEFAULT_EFFORT_HOURS[severity], tool=tool, rule_id=rule_id,
    )


def parse_pip_audit(stdout: str) -> list[Finding]:
    data = _loads(stdout)
    if not data:
        return []
    out = []
    for dep in data.get("dependencies", []):
        name, version = dep.get("name", "?"), dep.get("version", "?")
        for v in dep.get("vulns", []):
            fix = ", ".join(v.get("fix_versions", []) or []) or "no fix listed"
            out.append(_finding(
                Dimension.DEPENDENCIES, Severity.HIGH, f"{name}=={version}",
                v.get("description", "vulnerable dependency"), "pip-audit",
                v.get("id"), recommendation=f"Upgrade to: {fix}",
            ))
    return out


def parse_npm_audit(stdout: str) -> list[Finding]:
    data = _loads(stdout)
    if not data:
        return []
    out = []
    for name, info in (data.get("vulnerabilities") or {}).items():
        sev = _NPM_SEVERITY.get(info.get("severity", "low"), Severity.LOW)
        via = info.get("via", [])
        title = next((v.get("title") for v in via if isinstance(v, dict)),
                     "vulnerable dependency")
        out.append(_finding(
            Dimension.DEPENDENCIES, sev, f"{name}@{info.get('range', '?')}",
            title, "npm-audit", None,
            recommendation="Run `npm audit fix` or upgrade the package.",
        ))
    return out


def _exec(tool, inp, result) -> ToolExecution:
    return ToolExecution(tool_name=tool, input=inp, success=(result.error is None),
                         duration_ms=result.duration_ms, error=result.error)


def run_pip_audit(repo_path: str, settings: Settings):
    # pip-audit has no directory-scan flag: audit a requirements.txt if present,
    # otherwise audit the active environment (run with cwd=repo_path).
    req = os.path.join(repo_path, "requirements.txt")
    if os.path.exists(req):
        cmd = ["pip-audit", "--format", "json", "-r", req]
    else:
        cmd = ["pip-audit", "--format", "json"]
    r = run_cli(cmd, timeout=settings.tool_timeout, cwd=repo_path)
    return parse_pip_audit(r.stdout), _exec("pip-audit", {"path": repo_path}, r)


def run_npm_audit(repo_path: str, settings: Settings):
    r = run_cli(["npm", "audit", "--json"], timeout=settings.tool_timeout, cwd=repo_path)
    return parse_npm_audit(r.stdout), _exec("npm-audit", {"path": repo_path}, r)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dependency_tools.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inspector/tools/dependencies.py tests/test_dependency_tools.py
git commit -m "feat(inspector): add dependency audit wrappers"
```

---

## Task 6: Container tool (trivy)

**Files:**
- Create: `src/inspector/tools/container.py`
- Test: `tests/test_container_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_container_tools.py
import json
from inspector.schemas import Dimension, Severity
from inspector.tools.container import parse_trivy

TRIVY = json.dumps({
    "Results": [{
        "Target": "Dockerfile",
        "Vulnerabilities": [{
            "VulnerabilityID": "CVE-2021-1", "PkgName": "openssl",
            "Severity": "CRITICAL", "Title": "buffer overflow",
            "FixedVersion": "1.1.1k",
        }],
        "Misconfigurations": [{
            "ID": "DS002", "Title": "root user", "Severity": "HIGH",
            "Resolution": "USER nonroot",
        }],
    }]
})


def test_parse_trivy_vulns_and_misconfig():
    fs = parse_trivy(TRIVY)
    sevs = {f.rule_id: f.severity for f in fs}
    assert sevs["CVE-2021-1"] == Severity.CRITICAL
    assert sevs["DS002"] == Severity.HIGH
    assert all(f.dimension == Dimension.CONTAINER for f in fs)
    assert all(f.tool == "trivy" for f in fs)


def test_parse_trivy_tolerates_garbage():
    assert parse_trivy("") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_container_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `src/inspector/tools/container.py`**

```python
"""Container/infra: trivy filesystem+config scan of the repo (Dockerfile, IaC)."""
from __future__ import annotations

import json
from typing import Optional

from ..config import Settings
from ..schemas import DEFAULT_EFFORT_HOURS, Dimension, Finding, Severity, ToolExecution
from .base import run_cli

_TRIVY_SEVERITY = {
    "CRITICAL": Severity.CRITICAL, "HIGH": Severity.HIGH,
    "MEDIUM": Severity.MEDIUM, "LOW": Severity.LOW, "UNKNOWN": Severity.LOW,
}


def _loads(stdout: str) -> Optional[dict]:
    try:
        return json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None


def _f(severity, location, description, rule_id, recommendation=""):
    return Finding(
        dimension=Dimension.CONTAINER, severity=severity, location=location,
        description=description, recommendation=recommendation,
        effort_hours=DEFAULT_EFFORT_HOURS[severity], tool="trivy", rule_id=rule_id,
    )


def parse_trivy(stdout: str) -> list[Finding]:
    data = _loads(stdout)
    if not data:
        return []
    out = []
    for res in data.get("Results", []):
        target = res.get("Target", "?")
        for v in res.get("Vulnerabilities", []) or []:
            sev = _TRIVY_SEVERITY.get(v.get("Severity", "UNKNOWN"), Severity.LOW)
            fix = v.get("FixedVersion") or "no fix"
            out.append(_f(sev, f"{target}:{v.get('PkgName', '?')}",
                          v.get("Title", ""), v.get("VulnerabilityID"),
                          recommendation=f"Update to {fix}."))
        for m in res.get("Misconfigurations", []) or []:
            sev = _TRIVY_SEVERITY.get(m.get("Severity", "UNKNOWN"), Severity.LOW)
            out.append(_f(sev, target, m.get("Title", ""), m.get("ID"),
                          recommendation=m.get("Resolution", "")))
    return out


def run_trivy(repo_path: str, settings: Settings):
    r = run_cli(["trivy", "fs", "--scanners", "vuln,misconfig,secret",
                 "--format", "json", repo_path], timeout=settings.tool_timeout)
    exec_ = ToolExecution(tool_name="trivy", input={"path": repo_path},
                          success=(r.error is None), duration_ms=r.duration_ms,
                          error=r.error)
    return parse_trivy(r.stdout), exec_
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_container_tools.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inspector/tools/container.py tests/test_container_tools.py
git commit -m "feat(inspector): add trivy container wrapper"
```

---

## Task 7: Code-quality tool (SonarQube web API reader)

**Files:**
- Create: `src/inspector/tools/code_quality.py`
- Test: `tests/test_code_quality_tools.py`

The wrapper triggers `sonar-scanner` (best-effort) then reads issues from the
SonarQube web API. Parsing the API JSON is the pure, tested part. The HTTP call is
isolated behind a small injectable `fetch` function so the test passes a fake.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_code_quality_tools.py
from inspector.schemas import Dimension, Severity
from inspector.tools.code_quality import parse_sonar_issues, sonar_to_severity

SONAR = {
    "issues": [
        {"rule": "python:S1192", "severity": "MAJOR", "component": "proj:app.py",
         "line": 5, "message": "dup string", "effort": "10min", "type": "CODE_SMELL"},
        {"rule": "python:S2076", "severity": "BLOCKER", "component": "proj:os.py",
         "line": 9, "message": "command injection", "effort": "1h", "type": "BUG"},
    ]
}


def test_sonar_severity_mapping():
    assert sonar_to_severity("BLOCKER") == Severity.CRITICAL
    assert sonar_to_severity("MAJOR") == Severity.MEDIUM
    assert sonar_to_severity("INFO") == Severity.LOW


def test_parse_sonar_issues_effort_and_location():
    fs = parse_sonar_issues(SONAR)
    assert all(f.dimension == Dimension.CODE_QUALITY for f in fs)
    blocker = next(f for f in fs if f.rule_id == "python:S2076")
    assert blocker.severity == Severity.CRITICAL
    assert blocker.location == "os.py:9"     # component prefix stripped
    assert blocker.effort_hours == 1.0       # "1h" parsed
    smell = next(f for f in fs if f.rule_id == "python:S1192")
    assert abs(smell.effort_hours - (10 / 60)) < 1e-6   # "10min"


def test_parse_sonar_tolerates_empty():
    assert parse_sonar_issues({}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_code_quality_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `src/inspector/tools/code_quality.py`**

```python
"""Code quality: SonarQube. `sonar-scanner` runs the analysis against a running
Sonar server; we then read the issues via the web API. Findings come only from
Sonar. If the server is unreachable, the dimension degrades (handled by caller)."""
from __future__ import annotations

import re
from typing import Callable, Optional

from ..config import Settings
from ..schemas import Dimension, Finding, Severity, ToolExecution
from .base import run_cli

_SONAR_SEVERITY = {
    "BLOCKER": Severity.CRITICAL, "CRITICAL": Severity.HIGH,
    "MAJOR": Severity.MEDIUM, "MINOR": Severity.LOW, "INFO": Severity.LOW,
}


def sonar_to_severity(s: str) -> Severity:
    return _SONAR_SEVERITY.get((s or "").upper(), Severity.LOW)


def _effort_hours(effort: Optional[str]) -> float:
    """Sonar effort like '10min', '1h', '1h30min' → hours. Falls back to 0.5."""
    if not effort:
        return 0.5
    h = re.search(r"(\d+)h", effort)
    m = re.search(r"(\d+)min", effort)
    hours = (int(h.group(1)) if h else 0) + (int(m.group(1)) / 60 if m else 0)
    return hours or 0.5


def parse_sonar_issues(data: dict) -> list[Finding]:
    out = []
    for i in data.get("issues", []):
        sev = sonar_to_severity(i.get("severity", ""))
        component = i.get("component", "?")
        path = component.split(":", 1)[-1]  # strip "projectKey:" prefix
        loc = f"{path}:{i.get('line', 0)}"
        out.append(Finding(
            dimension=Dimension.CODE_QUALITY, severity=sev, location=loc,
            description=i.get("message", ""), recommendation="",
            effort_hours=_effort_hours(i.get("effort")), tool="sonarqube",
            rule_id=i.get("rule"),
        ))
    return out


def _default_fetch(settings: Settings) -> dict:
    """Read issues from the Sonar web API. Imported lazily so tests need no network."""
    import requests
    resp = requests.get(
        f"{settings.sonar_url}/api/issues/search",
        params={"componentKeys": settings.sonar_project_key, "ps": 500},
        auth=(settings.sonar_token, "") if settings.sonar_token else None,
        timeout=settings.llm_timeout,
    )
    resp.raise_for_status()
    return resp.json()


def run_sonar(repo_path: str, settings: Settings,
              fetch: Callable[[Settings], dict] = _default_fetch):
    """Trigger sonar-scanner (best-effort), then read issues from the API."""
    scan = run_cli(
        ["sonar-scanner",
         f"-Dsonar.projectKey={settings.sonar_project_key}",
         f"-Dsonar.sources=.",
         f"-Dsonar.host.url={settings.sonar_url}",
         f"-Dsonar.token={settings.sonar_token}"],
        timeout=settings.tool_timeout, cwd=repo_path,
    )
    try:
        data = fetch(settings)
    except Exception as exc:
        exec_ = ToolExecution(tool_name="sonarqube", input={"path": repo_path},
                              success=False, duration_ms=scan.duration_ms,
                              error=f"sonar API unreachable: {type(exc).__name__}: {exc}")
        return [], exec_
    exec_ = ToolExecution(tool_name="sonarqube", input={"path": repo_path},
                          success=True, duration_ms=scan.duration_ms, error=None)
    return parse_sonar_issues(data), exec_
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_code_quality_tools.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inspector/tools/code_quality.py tests/test_code_quality_tools.py
git commit -m "feat(inspector): add sonarqube code-quality reader"
```

---

## Task 8: Operational tools (ruff, dotenv-linter) + not-assessed list

**Files:**
- Create: `src/inspector/tools/operational.py`
- Test: `tests/test_operational_tools.py`

Operational uses ruff (broad lint incl. logging/bare-except/dead-code) and
dotenv-linter (config). bandit already runs in Security; operational reuses its
*parser* is unnecessary — keep ruff + dotenv here. Sub-checks with no tool
(graceful shutdown, container healthcheck) are returned as a fixed `NOT_ASSESSED`
list, never evaluated.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_operational_tools.py
import json
from inspector.schemas import Dimension, Severity
from inspector.tools.operational import parse_ruff, parse_dotenv_linter, NOT_ASSESSED

RUFF = json.dumps([
    {"code": "E722", "message": "do not use bare except", "filename": "a.py",
     "location": {"row": 3, "column": 1}, "url": "https://x"},
])


def test_parse_ruff():
    fs = parse_ruff(RUFF)
    assert fs[0].dimension == Dimension.OPERATIONAL
    assert fs[0].location == "a.py:3"
    assert fs[0].rule_id == "E722"
    assert fs[0].tool == "ruff"


def test_parse_dotenv_linter_text():
    out = ".env:2 LowercaseKey: The api_key key should be in uppercase"
    fs = parse_dotenv_linter(out)
    assert fs[0].dimension == Dimension.OPERATIONAL
    assert fs[0].location == ".env:2"
    assert fs[0].tool == "dotenv-linter"


def test_not_assessed_is_declared():
    assert any("shutdown" in x.lower() for x in NOT_ASSESSED)


def test_operational_parsers_tolerate_garbage():
    assert parse_ruff("") == []
    assert parse_dotenv_linter("") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_operational_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `src/inspector/tools/operational.py`**

```python
"""Operational readiness via named linters only: ruff (logging, bare-except,
dead code), dotenv-linter (config). Checks no tool covers (graceful shutdown,
container health-check) are listed in NOT_ASSESSED and never evaluated."""
from __future__ import annotations

import json
import re
from typing import Optional

from ..config import Settings
from ..schemas import DEFAULT_EFFORT_HOURS, Dimension, Finding, Severity, ToolExecution
from .base import run_cli

NOT_ASSESSED = [
    "Graceful shutdown handling (no off-the-shelf scanner)",
    "Container health-check presence (no off-the-shelf scanner)",
]

_DOTENV_RE = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+)\s+(?P<rule>\w+):\s*(?P<msg>.+)$")


def parse_ruff(stdout: str) -> list[Finding]:
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for r in data:
        loc = f"{r.get('filename', '?')}:{r.get('location', {}).get('row', 0)}"
        out.append(Finding(
            dimension=Dimension.OPERATIONAL, severity=Severity.MEDIUM, location=loc,
            description=r.get("message", ""), recommendation=r.get("url", "") or "",
            effort_hours=DEFAULT_EFFORT_HOURS[Severity.MEDIUM], tool="ruff",
            rule_id=r.get("code"),
        ))
    return out


def parse_dotenv_linter(stdout: str) -> list[Finding]:
    out = []
    for line in (stdout or "").splitlines():
        m = _DOTENV_RE.match(line.strip())
        if not m:
            continue
        out.append(Finding(
            dimension=Dimension.OPERATIONAL, severity=Severity.LOW,
            location=f"{m['file']}:{m['line']}", description=m["msg"],
            recommendation="", effort_hours=DEFAULT_EFFORT_HOURS[Severity.LOW],
            tool="dotenv-linter", rule_id=m["rule"],
        ))
    return out


def _exec(tool, inp, result) -> ToolExecution:
    return ToolExecution(tool_name=tool, input=inp, success=(result.error is None),
                         duration_ms=result.duration_ms, error=result.error)


def run_ruff(repo_path: str, settings: Settings):
    r = run_cli(["ruff", "check", "--output-format", "json", repo_path],
                timeout=settings.tool_timeout)
    return parse_ruff(r.stdout), _exec("ruff", {"path": repo_path}, r)


def run_dotenv_linter(repo_path: str, settings: Settings):
    r = run_cli(["dotenv-linter", repo_path], timeout=settings.tool_timeout)
    return parse_dotenv_linter(r.stdout), _exec("dotenv-linter", {"path": repo_path}, r)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_operational_tools.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inspector/tools/operational.py tests/test_operational_tools.py
git commit -m "feat(inspector): add operational linter wrappers"
```

---

## Task 9: LLM client (Protocol + OllamaLLM)

**Files:**
- Create: `src/inspector/llm.py`
- Test: `tests/test_llm.py`

Adapted from `multi-agent-debate-system/src/debate/llm.py`: grammar-constrained
JSON via Ollama `format=`, lenient extraction fallback, retry with error fed back.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm.py
from pydantic import BaseModel
from inspector.llm import extract_model


class Foo(BaseModel):
    a: int
    b: str


def test_extract_model_clean_json():
    assert extract_model('{"a": 1, "b": "x"}', Foo) == Foo(a=1, b="x")


def test_extract_model_embedded_json():
    txt = 'Here you go:\n{"a": 2, "b": "y"}\nthanks'
    assert extract_model(txt, Foo) == Foo(a=2, b="y")


def test_extract_model_returns_none_on_failure():
    assert extract_model("no json here", Foo) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `src/inspector/llm.py`**

```python
"""LLM access: grammar-constrained structured output over a local Ollama model.

Agents depend on the `LLMClient` Protocol, so tests inject a `FakeLLM` and the
whole graph runs with no model. Adapted from the debate system's llm.py.
"""
from __future__ import annotations

import json
import re
from typing import Protocol, Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class InspectorLLMError(RuntimeError):
    """Raised when a model call cannot produce a usable result after retries."""


def _iter_top_level_json(text: str):
    depth, start = 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                yield text[start:i + 1]


def _loads_lenient(fragment: str):
    try:
        return json.loads(fragment)
    except json.JSONDecodeError:
        fixed = re.sub(r'\\([^"\\/bfnrtu])', r"\1", fragment)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None


def extract_model(content: str, schema: Type[T]) -> T | None:
    try:
        return schema.model_validate_json(content)
    except ValidationError:
        pass
    for fragment in _iter_top_level_json(content):
        obj = _loads_lenient(fragment)
        if isinstance(obj, dict):
            try:
                return schema.model_validate(obj)
            except ValidationError:
                continue
    return None


class LLMClient(Protocol):
    def generate_json(self, system: str, user: str, schema: Type[T]) -> T: ...


class OllamaLLM:
    """Concrete `LLMClient` over a local Ollama server."""

    def __init__(self, model: str, *, timeout: float = 240.0, num_predict: int = 700,
                 retries: int = 2, log=None):
        self._model = model
        self._timeout = timeout
        self._num_predict = num_predict
        self._retries = retries
        self._log = log or (lambda *a, **k: None)

    def generate_json(self, system: str, user: str, schema: Type[T]) -> T:
        import ollama
        client = ollama.Client(timeout=self._timeout)
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        fmt = schema.model_json_schema()
        last_err = "no response"
        for attempt in range(self._retries + 1):
            try:
                resp = client.chat(model=self._model, messages=messages, format=fmt,
                                   options={"num_predict": self._num_predict})
            except Exception as exc:
                raise InspectorLLMError(
                    f"{self._model} call failed: {type(exc).__name__}: {exc}")
            content = resp["message"].get("content") or ""
            parsed = extract_model(content, schema)
            if parsed is not None:
                return parsed
            last_err = f"did not match {schema.__name__}: {content[:200]!r}"
            self._log("RETRY", f"attempt {attempt + 1}: {last_err}")
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content":
                f"That did not match the required JSON schema for {schema.__name__}. "
                f"Reply with ONLY a valid JSON object matching the schema."})
        raise InspectorLLMError(f"{self._model}: {last_err}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inspector/llm.py tests/test_llm.py
git commit -m "feat(inspector): add ollama llm client with structured output"
```

---

## Task 10: Observability (structured run logger)

**Files:**
- Create: `src/inspector/observability.py`
- Test: `tests/test_observability.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_observability.py
import json
from inspector.observability import RunLogger
from inspector.schemas import ToolExecution


def test_logs_tool_and_decision_as_json_lines(tmp_path):
    path = tmp_path / "run.jsonl"
    log = RunLogger(path, verbose=False)
    log.tool(ToolExecution(tool_name="bandit", input={"p": "."}, success=True,
                           duration_ms=12, error=None))
    log.decision("triage", {"security": "deep"}, "no tests found")
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    rec0 = json.loads(lines[0])
    assert rec0["event"] == "tool" and rec0["tool_name"] == "bandit"
    rec1 = json.loads(lines[1])
    assert rec1["event"] == "decision" and rec1["node"] == "triage"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_observability.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `src/inspector/observability.py`**

```python
"""Structured JSON run logging (spec Decision 6). One line per tool execution and
per LLM decision, so any report can be traced to exactly what was investigated."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

from .schemas import ToolExecution


class RunLogger:
    def __init__(self, path: Optional[Path] = None, verbose: bool = True):
        self._path = Path(path) if path else None
        self._verbose = verbose
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("")  # truncate per run

    def _emit(self, record: dict) -> None:
        record["ts"] = time.time()
        line = json.dumps(record)
        if self._path:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        if self._verbose:
            print(line, file=sys.stderr, flush=True)

    def tool(self, execution: ToolExecution) -> None:
        rec = {"event": "tool"}
        rec.update(execution.model_dump())
        self._emit(rec)

    def decision(self, node: str, choice, reason: str) -> None:
        self._emit({"event": "decision", "node": node, "choice": choice,
                    "reason": reason})

    def note(self, message: str) -> None:
        self._emit({"event": "note", "message": message})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_observability.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inspector/observability.py tests/test_observability.py
git commit -m "feat(inspector): add structured run logger"
```

---

## Task 11: Triage (signal detection + LLM depth plan)

**Files:**
- Create: `src/inspector/triage.py`
- Test: `tests/test_triage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_triage.py
from inspector.triage import detect_language, detect_signals


def test_detect_language_python(tmp_path):
    (tmp_path / "main.py").write_text("print(1)")
    assert detect_language(str(tmp_path)) == "python"


def test_detect_language_javascript(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert detect_language(str(tmp_path)) == "javascript"


def test_detect_language_unknown(tmp_path):
    (tmp_path / "readme.txt").write_text("hi")
    assert detect_language(str(tmp_path)) == "unknown"


def test_detect_signals_reports_dockerfile(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python")
    (tmp_path / "main.py").write_text("x=1")
    sig = detect_signals(str(tmp_path))
    assert sig["has_dockerfile"] is True
    assert sig["language"] == "python"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_triage.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `src/inspector/triage.py`**

```python
"""Triage node: detect cheap repo signals (deterministic), then let the LLM pick
per-dimension investigation depth (control only — never produces findings)."""
from __future__ import annotations

import os
from typing import Optional

from .config import Settings
from .llm import InspectorLLMError, LLMClient
from .schemas import DepthPlan, InspectionState

_DEPTHS = {"deep", "standard", "skip"}


def detect_language(repo_path: str) -> str:
    py = js = 0
    for root, _dirs, files in os.walk(repo_path):
        if any(skip in root for skip in (".git", "node_modules", ".venv")):
            continue
        for f in files:
            if f.endswith(".py"):
                py += 1
            elif f.endswith((".js", ".ts", ".jsx", ".tsx")):
                js += 1
            if f == "package.json":
                js += 5
    if py == 0 and js == 0:
        return "unknown"
    return "python" if py >= js else "javascript"


def detect_signals(repo_path: str) -> dict:
    entries = set()
    for root, _dirs, files in os.walk(repo_path):
        if ".git" in root:
            continue
        for f in files:
            entries.add(f.lower())
    return {
        "language": detect_language(repo_path),
        "has_dockerfile": "dockerfile" in entries
        or any(e.endswith("docker-compose.yml") or e == "docker-compose.yml"
               for e in entries),
        "has_coverage": any(e in entries for e in ("coverage.xml", ".coverage")),
        "has_env": any(e == ".env" or e.endswith(".env") for e in entries),
    }


_TRIAGE_SYSTEM = (
    "You plan a production-readiness audit. Given repo signals, decide how deeply to "
    "investigate each of five dimensions. Reply ONLY as JSON matching the schema, each "
    "value one of: deep, standard, skip. You do NOT analyse code — you only choose "
    "depth. Skip 'container' if there is no Dockerfile. Prefer 'deep' code_quality when "
    "there is no coverage. Never skip security."
)


def _fallback_plan() -> dict[str, str]:
    return {d: "standard" for d in
            ("security", "code_quality", "container", "dependencies", "operational")}


def make_triage_node(client: LLMClient, settings: Settings, log=None):
    def triage(state: InspectionState) -> dict:
        signals = detect_signals(state["repo_path"])
        user = f"Repo signals: {signals}. Choose investigation depth per dimension."
        try:
            plan_model: DepthPlan = client.generate_json(_TRIAGE_SYSTEM, user, DepthPlan)
            plan = {k: (v if v in _DEPTHS else "standard")
                    for k, v in plan_model.model_dump().items()}
        except InspectorLLMError:
            plan = _fallback_plan()
        if not signals["has_dockerfile"]:
            plan["container"] = "skip"
        if log:
            log.decision("triage", plan, f"signals={signals}")
        return {"repo_language": signals["language"], "depth_plan": plan}
    return triage
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_triage.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inspector/triage.py tests/test_triage.py
git commit -m "feat(inspector): add triage node with signal detection"
```

---

## Task 12: Prioritisation (deterministic ordering)

**Files:**
- Create: `src/inspector/prioritize.py`
- Test: `tests/test_prioritize.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prioritize.py
from inspector.schemas import Dimension, Finding, Severity
from inspector.prioritize import path_criticality, prioritise


def _f(sev, loc, effort, tool="t"):
    return Finding(dimension=Dimension.SECURITY, severity=sev, location=loc,
                   description="d", recommendation="r", effort_hours=effort, tool=tool)


def test_path_criticality_boosts_auth_files():
    assert path_criticality("src/auth/login.py:1") > path_criticality("src/util.py:1")


def test_prioritise_orders_high_risk_low_effort_first():
    findings = [
        _f(Severity.LOW, "util.py:1", 1.0),
        _f(Severity.CRITICAL, "auth/login.py:1", 1.0),
        _f(Severity.CRITICAL, "util.py:2", 8.0),
    ]
    plan = prioritise(findings)
    assert plan[0].rank == 1
    assert plan[0].finding.location == "auth/login.py:1"   # critical + critical path
    assert [s.rank for s in plan] == [1, 2, 3]


def test_prioritise_empty():
    assert prioritise([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prioritize.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `src/inspector/prioritize.py`**

```python
"""Deterministic risk-adjusted ordering over tool-produced findings (Decision 4).
risk = severity_weight * path_criticality / max(effort, 0.5). Pure functions."""
from __future__ import annotations

from .schemas import SEVERITY_WEIGHT, Finding, RemediationStep

_CRITICAL_PATH_MARKERS = ("auth", "login", "security", "secret", "credential",
                          "main", "app", "config", "settings", "server", "api",
                          "payment", "admin")


def path_criticality(location: str) -> float:
    low = location.lower()
    return 2.0 if any(m in low for m in _CRITICAL_PATH_MARKERS) else 1.0


def risk_score(f: Finding) -> float:
    return SEVERITY_WEIGHT[f.severity] * path_criticality(f.location) / max(f.effort_hours, 0.5)


def prioritise(findings: list[Finding]) -> list[RemediationStep]:
    ranked = sorted(findings, key=risk_score, reverse=True)
    steps = []
    for i, f in enumerate(ranked, start=1):
        crit = path_criticality(f.location) > 1.0
        rationale = (
            f"{f.severity.value} severity from {f.tool}"
            f"{' in a critical code path' if crit else ''}; "
            f"~{f.effort_hours:.1f}h to fix (risk score {risk_score(f):.1f})."
        )
        steps.append(RemediationStep(rank=i, finding=f, risk_score=risk_score(f),
                                     rationale=rationale))
    return steps
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_prioritize.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inspector/prioritize.py tests/test_prioritize.py
git commit -m "feat(inspector): add deterministic prioritisation"
```

---

## Task 13: Dimension + synthesise nodes

**Files:**
- Create: `src/inspector/nodes.py`
- Test: `tests/test_nodes.py`

Each dimension node runs its tool wrappers (respecting `depth_plan` skip), returns
`{"findings": [...], "tools_run": [...]}`. The synthesise node builds the `Report`:
prioritisation in code, executive summary from the LLM (with a code fallback).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_nodes.py
from inspector.schemas import Dimension, Finding, Severity, ExecutiveSummary
from inspector.nodes import make_synthesise_node, _build_report


def _f(sev, dim=Dimension.SECURITY):
    return Finding(dimension=dim, severity=sev, location="app.py:1", description="d",
                   recommendation="r", effort_hours=1.0, tool="bandit")


class FakeLLM:
    def __init__(self, summary="All clear."):
        self._summary = summary
    def generate_json(self, system, user, schema):
        return ExecutiveSummary(summary=self._summary)


def test_build_report_counts_and_orders():
    findings = [_f(Severity.CRITICAL), _f(Severity.LOW)]
    report = _build_report("repo", "python", findings, [], [], "Summary.")
    assert report.critical_count == 1
    assert report.findings_by_severity[Severity.CRITICAL] == 1
    assert report.prioritised_remediation_plan[0].finding.severity == Severity.CRITICAL
    assert report.estimated_total_effort_hours == 2.0


def test_synthesise_node_uses_llm_summary():
    node = make_synthesise_node(FakeLLM("Two issues, fix the critical first."))
    state = {"repo_path": "r", "repo_language": "python",
             "findings": [_f(Severity.CRITICAL)], "tools_run": [], "not_assessed": []}
    out = node(state)
    assert "critical" in out["report"].executive_summary.lower()


def test_synthesise_falls_back_when_llm_raises():
    class Boom:
        def generate_json(self, *a): raise RuntimeError("down")
    node = make_synthesise_node(Boom())
    state = {"repo_path": "r", "repo_language": "python",
             "findings": [_f(Severity.HIGH)], "tools_run": [], "not_assessed": []}
    out = node(state)
    assert out["report"].executive_summary  # non-empty code fallback
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nodes.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `src/inspector/nodes.py`**

```python
"""Dimension nodes (run tools) and the synthesise node (build the Report).

Findings come only from tool wrappers. The LLM writes the executive summary; if it
fails, a deterministic summary is used so a report is always produced."""
from __future__ import annotations

from collections import Counter

from .config import Settings
from .llm import LLMClient
from .observability import RunLogger
from .prioritize import prioritise
from .schemas import (
    Dimension, ExecutiveSummary, Finding, InspectionState, Report, Severity,
    ToolExecution,
)
from .tools import code_quality, container, dependencies, operational, security
from .tools.operational import NOT_ASSESSED


def _run_tools(runners, repo_path, settings, log) -> dict:
    findings: list[Finding] = []
    execs: list[ToolExecution] = []
    for runner in runners:
        fs, ex = runner(repo_path, settings)
        findings.extend(fs)
        execs.append(ex)
        if log:
            log.tool(ex)
    return {"findings": findings, "tools_run": execs}


def _skip(state: InspectionState, dimension: Dimension) -> bool:
    return state.get("depth_plan", {}).get(dimension.value) == "skip"


def make_dimension_nodes(settings: Settings, log: RunLogger | None = None):
    def security_node(state: InspectionState) -> dict:
        if _skip(state, Dimension.SECURITY):
            return {}
        return _run_tools(
            [security.run_semgrep, security.run_detect_secrets, security.run_bandit],
            state["repo_path"], settings, log)

    def code_quality_node(state: InspectionState) -> dict:
        if _skip(state, Dimension.CODE_QUALITY):
            return {}
        fs, ex = code_quality.run_sonar(state["repo_path"], settings)
        if log:
            log.tool(ex)
        return {"findings": fs, "tools_run": [ex]}

    def container_node(state: InspectionState) -> dict:
        if _skip(state, Dimension.CONTAINER):
            return {}
        fs, ex = container.run_trivy(state["repo_path"], settings)
        if log:
            log.tool(ex)
        return {"findings": fs, "tools_run": [ex]}

    def dependencies_node(state: InspectionState) -> dict:
        if _skip(state, Dimension.DEPENDENCIES):
            return {}
        runners = ([dependencies.run_pip_audit] if state.get("repo_language") == "python"
                   else [dependencies.run_npm_audit])
        return _run_tools(runners, state["repo_path"], settings, log)

    def operational_node(state: InspectionState) -> dict:
        if _skip(state, Dimension.OPERATIONAL):
            return {"not_assessed": list(NOT_ASSESSED)}
        out = _run_tools([operational.run_ruff, operational.run_dotenv_linter],
                         state["repo_path"], settings, log)
        out["not_assessed"] = list(NOT_ASSESSED)
        return out

    return {
        "security": security_node, "code_quality": code_quality_node,
        "container": container_node, "dependencies": dependencies_node,
        "operational": operational_node,
    }


_SUMMARY_SYSTEM = (
    "You write a 3-sentence executive summary of a production-readiness audit. You are "
    "given a list of findings ALL produced by analysis tools. Summarise their overall "
    "state and what to fix first. Do NOT invent findings or numbers not in the list. "
    "Reply ONLY as JSON matching the schema."
)


def _fallback_summary(findings: list[Finding]) -> str:
    counts = Counter(f.severity for f in findings)
    crit, high = counts[Severity.CRITICAL], counts[Severity.HIGH]
    if not findings:
        return "No findings were produced by the configured tools."
    return (f"{len(findings)} findings ({crit} critical, {high} high). "
            f"Address critical items in critical code paths first.")


def _build_report(repo_path, repo_language, findings, tools_run, not_assessed,
                  summary) -> Report:
    counts = Counter(f.severity for f in findings)
    plan = prioritise(findings)
    skipped = [ex for ex in tools_run if not ex.success]
    return Report(
        executive_summary=summary, repo_path=repo_path, repo_language=repo_language,
        critical_count=counts[Severity.CRITICAL],
        findings_by_severity={s: counts[s] for s in Severity if counts[s]},
        prioritised_remediation_plan=plan,
        estimated_total_effort_hours=round(sum(f.effort_hours for f in findings), 1),
        skipped=skipped, not_assessed=list(not_assessed),
    )


def make_synthesise_node(client: LLMClient, log: RunLogger | None = None):
    def synthesise(state: InspectionState) -> dict:
        findings = state.get("findings", [])
        digest = "\n".join(
            f"- [{f.severity.value}] {f.dimension.value} {f.location}: {f.description}"
            for f in findings[:60]) or "(no findings)"
        try:
            model: ExecutiveSummary = client.generate_json(
                _SUMMARY_SYSTEM, f"Findings:\n{digest}", ExecutiveSummary)
            summary = model.summary
        except Exception:
            summary = _fallback_summary(findings)
        report = _build_report(
            state["repo_path"], state.get("repo_language", "unknown"), findings,
            state.get("tools_run", []), state.get("not_assessed", []), summary)
        if log:
            log.note(f"report built: {report.critical_count} critical, "
                     f"{len(findings)} findings")
        return {"report": report}
    return synthesise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nodes.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inspector/nodes.py tests/test_nodes.py
git commit -m "feat(inspector): add dimension and synthesise nodes"
```

---

## Task 14: Graph wiring

**Files:**
- Create: `src/inspector/graph.py`
- Test: `tests/conftest.py`, `tests/test_graph.py`

- [ ] **Step 1: Write `tests/conftest.py` (FakeLLM)**

```python
# tests/conftest.py
import pytest
from inspector.schemas import DepthPlan, ExecutiveSummary


class FakeLLM:
    """Returns valid instances of whatever schema is asked for. No model needed."""
    def __init__(self, depths="standard", summary="Audit complete."):
        self._depths = depths
        self._summary = summary
    def generate_json(self, system, user, schema):
        if schema is DepthPlan:
            return DepthPlan(security=self._depths, code_quality=self._depths,
                             container=self._depths, dependencies=self._depths,
                             operational=self._depths)
        if schema is ExecutiveSummary:
            return ExecutiveSummary(summary=self._summary)
        raise AssertionError(f"unexpected schema {schema}")


@pytest.fixture
def fake_llm():
    return FakeLLM()
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_graph.py
from inspector.config import Settings
from inspector.graph import build_graph


def test_graph_runs_end_to_end_with_fake_llm(monkeypatch, tmp_path, fake_llm):
    # A tiny python repo; stub every tool runner so no real scanners are needed.
    (tmp_path / "main.py").write_text("import os\nx=eval('1')\n")
    import inspector.nodes as nodes
    from inspector.schemas import Dimension, Finding, Severity, ToolExecution

    def fake_runner(name):
        def run(repo_path, settings):
            f = Finding(dimension=Dimension.SECURITY, severity=Severity.HIGH,
                        location="main.py:2", description="eval", recommendation="x",
                        effort_hours=1.0, tool=name)
            ex = ToolExecution(tool_name=name, input={}, success=True,
                               duration_ms=1, error=None)
            return [f], ex
        return run

    for mod, attr in [(nodes.security, "run_semgrep"), (nodes.security, "run_detect_secrets"),
                      (nodes.security, "run_bandit"), (nodes.dependencies, "run_pip_audit"),
                      (nodes.operational, "run_ruff"), (nodes.operational, "run_dotenv_linter")]:
        monkeypatch.setattr(mod, attr, fake_runner(attr))
    monkeypatch.setattr(nodes.code_quality, "run_sonar",
                        lambda p, s: ([], __import__("inspector.schemas", fromlist=["ToolExecution"]).ToolExecution(
                            tool_name="sonarqube", input={}, success=True, duration_ms=1, error=None)))
    monkeypatch.setattr(nodes.container, "run_trivy",
                        lambda p, s: ([], nodes.ToolExecution(tool_name="trivy", input={}, success=True, duration_ms=1, error=None)))

    graph = build_graph(fake_llm, Settings(verbose=False))
    final = graph.invoke({
        "repo_path": str(tmp_path), "repo_language": "", "depth_plan": {},
        "findings": [], "tools_run": [], "not_assessed": [], "report": None,
    })
    assert final["report"] is not None
    assert final["report"].repo_language == "python"
    assert len(final["report"].prioritised_remediation_plan) >= 1
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_graph.py -v`
Expected: FAIL with `ModuleNotFoundError: inspector.graph`

- [ ] **Step 4: Write `src/inspector/graph.py`**

```python
"""LangGraph wiring: triage → five dimension nodes (sequential) → synthesise → END.

Sequential per spec Decision 1; the reducer-backed state means switching to
parallel dimension fan-out later needs no schema change."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .config import Settings
from .llm import LLMClient
from .nodes import make_dimension_nodes, make_synthesise_node
from .observability import RunLogger
from .schemas import InspectionState
from .triage import make_triage_node


def build_graph(client: LLMClient, settings: Settings, log: RunLogger | None = None):
    g = StateGraph(InspectionState)
    g.add_node("triage", make_triage_node(client, settings, log))
    dims = make_dimension_nodes(settings, log)
    for name, fn in dims.items():
        g.add_node(name, fn)
    g.add_node("synthesise", make_synthesise_node(client, log))

    order = ["security", "code_quality", "container", "dependencies", "operational"]
    g.add_edge(START, "triage")
    g.add_edge("triage", order[0])
    for a, b in zip(order, order[1:]):
        g.add_edge(a, b)
    g.add_edge(order[-1], "synthesise")
    g.add_edge("synthesise", END)
    return g.compile()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_graph.py -v`
Expected: PASS (1 passed)

- [ ] **Step 6: Commit**

```bash
git add src/inspector/graph.py tests/conftest.py tests/test_graph.py
git commit -m "feat(inspector): wire langgraph inspection graph"
```

---

## Task 15: Report renderers

**Files:**
- Create: `src/inspector/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report.py
import json
from inspector.schemas import (Dimension, Finding, RemediationStep, Report, Severity)
from inspector.report import render_json, render_markdown


def _report():
    f = Finding(dimension=Dimension.SECURITY, severity=Severity.CRITICAL,
                location="auth.py:3", description="hardcoded key", recommendation="rotate",
                effort_hours=2.0, tool="detect-secrets", rule_id=None)
    step = RemediationStep(rank=1, finding=f, risk_score=8.0, rationale="critical path")
    return Report(executive_summary="One critical issue.", repo_path="r",
                  repo_language="python", critical_count=1,
                  findings_by_severity={Severity.CRITICAL: 1},
                  prioritised_remediation_plan=[step], estimated_total_effort_hours=2.0,
                  skipped=[], not_assessed=["Graceful shutdown"])


def test_render_json_is_valid_and_round_trips():
    out = render_json(_report())
    data = json.loads(out)
    assert data["critical_count"] == 1
    assert data["prioritised_remediation_plan"][0]["rank"] == 1


def test_render_markdown_has_summary_and_plan():
    md = render_markdown(_report())
    assert "One critical issue." in md
    assert "auth.py:3" in md
    assert "Not assessed" in md
    assert "#1" in md or "1." in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `src/inspector/report.py`**

```python
"""Render a Report as JSON (machine) or markdown (human). The markdown is the
product: summary, counts, the prioritised plan, skipped tools, not-assessed."""
from __future__ import annotations

from .schemas import Report, Severity

_SEV_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]


def render_json(report: Report) -> str:
    return report.model_dump_json(indent=2)


def render_markdown(report: Report) -> str:
    lines = [
        f"# Production-Readiness Report — `{report.repo_path}`",
        "",
        f"**Language:** {report.repo_language}  |  "
        f"**Critical:** {report.critical_count}  |  "
        f"**Est. total effort:** {report.estimated_total_effort_hours}h",
        "",
        "## Executive summary",
        report.executive_summary,
        "",
        "## Findings by severity",
    ]
    for sev in _SEV_ORDER:
        n = report.findings_by_severity.get(sev, 0)
        if n:
            lines.append(f"- **{sev.value}**: {n}")
    lines += ["", "## Prioritised remediation plan", ""]
    if not report.prioritised_remediation_plan:
        lines.append("_No findings._")
    for step in report.prioritised_remediation_plan:
        f = step.finding
        rule = f" ({f.rule_id})" if f.rule_id else ""
        lines += [
            f"### #{step.rank} — [{f.severity.value}] {f.location}{rule}",
            f"- **Dimension:** {f.dimension.value}  ·  **Tool:** {f.tool}  ·  "
            f"**Effort:** ~{f.effort_hours}h  ·  **Risk:** {step.risk_score:.1f}",
            f"- **Issue:** {f.description}",
            f"- **Fix:** {f.recommendation or '(see tool output)'}",
            f"- _{step.rationale}_",
            "",
        ]
    if report.skipped:
        lines += ["## Tools that failed / were skipped", ""]
        for ex in report.skipped:
            lines.append(f"- `{ex.tool_name}`: {ex.error or 'no output'}")
        lines.append("")
    if report.not_assessed:
        lines += ["## Not assessed (no dedicated tool)", ""]
        for item in report.not_assessed:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_report.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inspector/report.py tests/test_report.py
git commit -m "feat(inspector): add json and markdown report renderers"
```

---

## Task 16: CLI entrypoint

**Files:**
- Create: `main.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import sys
from inspector.config import Settings
from main import build_parser, run_inspection


def test_parser_defaults():
    args = build_parser().parse_args(["inspect", "somepath"])
    assert args.repo_path == "somepath"
    assert args.format == "md"


def test_run_inspection_returns_rendered_report(monkeypatch, tmp_path, fake_llm):
    (tmp_path / "main.py").write_text("x=1\n")
    # Stub the graph so no real scanners/LLM run; return a state with a report.
    import main as main_mod
    from inspector.schemas import Report

    class FakeGraph:
        def invoke(self, state):
            state = dict(state)
            state["report"] = Report(
                executive_summary="ok", repo_path=str(tmp_path),
                repo_language="python", critical_count=0, findings_by_severity={},
                prioritised_remediation_plan=[], estimated_total_effort_hours=0.0,
                skipped=[], not_assessed=[])
            return state

    monkeypatch.setattr(main_mod, "build_graph", lambda c, s, log=None: FakeGraph())
    out = run_inspection(str(tmp_path), fmt="md", settings=Settings(verbose=False),
                         client=fake_llm)
    assert "Executive summary" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Write `main.py`**

```python
"""CLI entrypoint for the Agentic Pipeline Inspector.

    python main.py inspect <repo_path> [--format json|md] [--model M] [--out F] [--verbose]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inspector.config import Settings
from inspector.graph import build_graph
from inspector.llm import LLMClient, OllamaLLM
from inspector.observability import RunLogger
from inspector.report import render_json, render_markdown


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="inspector", description="Production-readiness auditor")
    sub = p.add_subparsers(dest="command", required=True)
    insp = sub.add_parser("inspect", help="inspect a repository")
    insp.add_argument("repo_path")
    insp.add_argument("--format", choices=["json", "md"], default="md")
    insp.add_argument("--model", default=None)
    insp.add_argument("--out", default=None)
    insp.add_argument("--verbose", action="store_true")
    return p


def run_inspection(repo_path: str, fmt: str, settings: Settings,
                   client: LLMClient, log: RunLogger | None = None) -> str:
    graph = build_graph(client, settings, log=log)
    initial = {"repo_path": repo_path, "repo_language": "", "depth_plan": {},
               "findings": [], "tools_run": [], "not_assessed": [], "report": None}
    final = graph.invoke(initial)
    report = final["report"]
    return render_json(report) if fmt == "json" else render_markdown(report)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not Path(args.repo_path).is_dir():
        print(f"error: not a directory: {args.repo_path}", file=sys.stderr)
        return 2
    settings = Settings(model=args.model or Settings.model, verbose=args.verbose)
    settings.validate()
    log = RunLogger(Path("inspector_run.jsonl"), verbose=args.verbose)
    client = OllamaLLM(settings.model, timeout=settings.llm_timeout,
                       num_predict=settings.llm_num_predict,
                       retries=settings.validation_retries,
                       log=lambda *a: log.note(" ".join(map(str, a))))
    output = run_inspection(args.repo_path, args.format, settings, client, log)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"report written to {args.out}", file=sys.stderr)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_cli.py
git commit -m "feat(inspector): add CLI entrypoint"
```

---

## Task 17: Tool installation (real scanners)

This task installs the real scanners so the agent can run against live repos.
**Each install command modifies the global environment — confirm with the user
before running each one.**

- [ ] **Step 1: Install Python scanners**

Run: `pip install -r requirements.txt`
Expected: semgrep, detect-secrets, bandit, pip-audit, ruff installed. (On Windows,
`semgrep` may be unavailable as a wheel; if it fails, note it — the agent degrades
gracefully when semgrep is absent.)

- [ ] **Step 2: Install trivy**

Run: `winget install AquaSecurity.Trivy`
Verify: `trivy --version`

- [ ] **Step 3: Install dotenv-linter**

Run: `winget install dotenv-linter.dotenv-linter` (or download the release binary)
Verify: `dotenv-linter --version`

- [ ] **Step 4: Start SonarQube + install sonar-scanner**

Run: `docker run -d --name sonarqube -p 9000:9000 sonarqube:community`
Then create a token in the Sonar UI (http://localhost:9000, admin/admin) and set
`SONAR_TOKEN`, `SONAR_URL`, `SONAR_PROJECT_KEY` env vars. Install `sonar-scanner`
CLI and verify: `sonar-scanner --version`.

- [ ] **Step 5: Confirm Ollama model**

Run: `ollama list`
Expected: `qwen2.5:3b` present (already pulled).

---

## Task 18: Eval harness (3 reference repos)

**Files:**
- Create: `eval/run_eval.py`, `eval/repos.md`

- [ ] **Step 1: Write `eval/repos.md`**

```markdown
# Reference repos (spec §13)

1. **Well-maintained OSS** — expect a short, low-severity list.
   e.g. clone `https://github.com/pallets/click`
2. **Intentionally vulnerable** — expect all critical security issues surfaced.
   e.g. clone `https://github.com/digininja/DVWA` (PHP — for JS/py pick
   `https://github.com/OWASP/NodeGoat`)
3. **User's own project** — expect genuinely actionable feedback.

Run each: `python main.py inspect <clone_path> --format md --out eval/out_<name>.md`
```

- [ ] **Step 2: Write `eval/run_eval.py`**

```python
"""Run the inspector against a list of repo paths and write a report per repo.

Usage: python eval/run_eval.py <repo_path> [<repo_path> ...]
This drives the REAL agent (real scanners + Ollama). It is an integration runner,
not a unit test — it needs the tools from Task 17 installed."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inspector.config import Settings           # noqa: E402
from inspector.llm import OllamaLLM             # noqa: E402
from inspector.observability import RunLogger   # noqa: E402
from main import run_inspection                 # noqa: E402


def main(paths: list[str]) -> int:
    settings = Settings(verbose=True)
    settings.validate()
    out_dir = Path(__file__).parent
    for p in paths:
        name = Path(p).name
        log = RunLogger(out_dir / f"run_{name}.jsonl", verbose=True)
        client = OllamaLLM(settings.model, timeout=settings.llm_timeout,
                           num_predict=settings.llm_num_predict)
        md = run_inspection(p, "md", settings, client, log)
        (out_dir / f"out_{name}.md").write_text(md, encoding="utf-8")
        print(f"[eval] wrote out_{name}.md")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python eval/run_eval.py <repo_path> [...]", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 3: Commit**

```bash
git add eval/
git commit -m "feat(inspector): add eval harness for reference repos"
```

---

## Task 19: Docs (DESIGN.md, TECHNICAL_DEEP_DIVE.md)

**Files:**
- Create: `docs/DESIGN.md`, `docs/TECHNICAL_DEEP_DIVE.md`

- [ ] **Step 1: Write `docs/DESIGN.md`**

Summarise the spec for a reader: the five dimensions, the LangGraph flow diagram,
the "findings only from tools / LLM only orchestrates + summarises" guarantee, the
six spec decisions and how each is resolved. Link to the spec file. (Prose — no
code blocks required; 1–2 pages.)

- [ ] **Step 2: Write `docs/TECHNICAL_DEEP_DIVE.md`**

Explain the hard parts: the never-raising `run_cli` and graceful degradation
(Decision 3); grammar-constrained LLM JSON + FakeLLM testing; the deterministic
prioritisation formula and why prioritisation is code not LLM (Decision 4); the
SonarQube server dependency and how the dimension degrades when it's down; the
provenance guarantee (`Finding.tool`) and the `not_assessed` honesty mechanism.

- [ ] **Step 3: Commit**

```bash
git add docs/DESIGN.md docs/TECHNICAL_DEEP_DIVE.md
git commit -m "docs(inspector): add design and technical deep-dive"
```

---

## Task 20: Final verification

- [ ] **Step 1: Run the whole unit suite**

Run: `pytest -q`
Expected: all green. These tests use FakeLLM + stubbed runners — no scanners or
Ollama needed.

- [ ] **Step 2: Smoke-test the CLI against this inspector's own repo**

Run: `python main.py inspect . --format md --out self_report.md --verbose`
Expected: a markdown report is produced. Tools that aren't installed appear under
"Tools that failed / were skipped" — the run does not crash. (Requires at least
Ollama running; if not, triage/summary fall back and a report is still produced.)

- [ ] **Step 3: Review `self_report.md`** for sanity, then delete it.

Run: `rm self_report.md inspector_run.jsonl`

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore(inspector): final verification pass"
```

---

## Self-review notes (author)

- **Spec coverage:** 5 dimensions (Tasks 4–8), triage/depth (11), prioritisation
  (12), observability (10), structured output JSON+md (15), graceful degradation
  (3, throughout), LLM-only-orchestrates guarantee (9/11/13), eval vs 3 repos (18),
  docs (19). All spec sections map to a task.
- **Provenance guarantee:** every `Finding` carries `tool`; no parser invents data;
  uncovered checks go to `not_assessed`. Honoured in Tasks 4–8, 13, 15.
- **Type consistency:** `run(repo_path, settings) -> (list[Finding], ToolExecution)`
  uniform across all wrappers; node names match graph edges and `Dimension` values;
  `generate_json(system, user, schema)` uniform across OllamaLLM/FakeLLM.
