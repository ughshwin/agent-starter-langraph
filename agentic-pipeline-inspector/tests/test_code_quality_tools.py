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
