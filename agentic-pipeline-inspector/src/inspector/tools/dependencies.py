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
