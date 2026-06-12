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
