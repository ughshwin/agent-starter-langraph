"""Container/infra: trivy filesystem+config scan of the repo (Dockerfile, IaC)."""
from __future__ import annotations

import json
from typing import Optional

from ..config import Settings
from ..schemas import DEFAULT_EFFORT_HOURS, Dimension, Finding, Severity, ToolExecution
from .base import EXCLUDE_DIRS, run_cli

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
        for s in res.get("Secrets", []) or []:
            sev = _TRIVY_SEVERITY.get(s.get("Severity", "UNKNOWN"), Severity.HIGH)
            loc = f"{target}:{s.get('StartLine', 0)}"
            out.append(_f(sev, loc, s.get("Title", "exposed secret"), s.get("RuleID"),
                          recommendation="Remove the secret and rotate the credential."))
    return out


def run_trivy(repo_path: str, settings: Settings):
    skip = []
    for d in EXCLUDE_DIRS:
        skip += ["--skip-dirs", d]
    r = run_cli(["trivy", "fs", "--scanners", "vuln,misconfig,secret",
                 "--format", "json", *skip, repo_path], timeout=settings.tool_timeout)
    exec_ = ToolExecution(tool_name="trivy", input={"path": repo_path},
                          success=(r.error is None), duration_ms=r.duration_ms,
                          error=r.error)
    return parse_trivy(r.stdout), exec_
