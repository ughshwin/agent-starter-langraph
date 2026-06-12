import json

from inspector.report import render_json, render_markdown
from inspector.schemas import (Dimension, Finding, RemediationStep, Report,
                               Severity)


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
    assert "#1" in md
