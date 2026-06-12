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
