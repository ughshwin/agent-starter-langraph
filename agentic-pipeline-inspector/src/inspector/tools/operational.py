"""Operational readiness via named linters only: ruff (logging, bare-except,
dead code), dotenv-linter (config). Checks no tool covers (graceful shutdown,
container health-check) are listed in NOT_ASSESSED and never evaluated."""
from __future__ import annotations

import json
import re

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
