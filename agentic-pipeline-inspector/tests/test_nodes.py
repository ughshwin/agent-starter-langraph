import os

from inspector.nodes import (_build_report, make_synthesise_node,
                             relativize_location)
from inspector.schemas import Dimension, ExecutiveSummary, Finding, Severity


def _f(sev, dim=Dimension.SECURITY, loc="app.py:1"):
    return Finding(dimension=dim, severity=sev, location=loc, description="d",
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
        def generate_json(self, *a):
            raise RuntimeError("down")

    node = make_synthesise_node(Boom())
    state = {"repo_path": "r", "repo_language": "python",
             "findings": [_f(Severity.HIGH)], "tools_run": [], "not_assessed": []}
    out = node(state)
    assert out["report"].executive_summary  # non-empty code fallback


def test_relativize_location_makes_paths_relative(tmp_path):
    abs_file = os.path.join(str(tmp_path), "sub", "main.py")
    loc = f"{abs_file}:25"
    assert relativize_location(loc, str(tmp_path)) == "sub/main.py:25"


def test_relativize_leaves_non_paths_untouched(tmp_path):
    # dependency-style locations are not file paths and must be preserved
    assert relativize_location("flask==0.5", str(tmp_path)) == "flask==0.5"
    assert relativize_location("lodash@<4.17.12", str(tmp_path)) == "lodash@<4.17.12"


def test_relativize_leaves_outside_paths_untouched(tmp_path):
    assert relativize_location("Dockerfile:openssl", str(tmp_path)) == "Dockerfile:openssl"
