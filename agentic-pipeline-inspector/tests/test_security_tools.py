import json

from inspector.schemas import Dimension, Severity
from inspector.tools.security import parse_bandit, parse_detect_secrets, parse_semgrep

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
