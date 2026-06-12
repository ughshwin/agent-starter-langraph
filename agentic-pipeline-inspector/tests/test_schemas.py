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
