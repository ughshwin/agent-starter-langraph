import json

from inspector.schemas import Dimension, Severity
from inspector.tools.container import parse_trivy

TRIVY = json.dumps({
    "Results": [{
        "Target": "Dockerfile",
        "Vulnerabilities": [{
            "VulnerabilityID": "CVE-2021-1", "PkgName": "openssl",
            "Severity": "CRITICAL", "Title": "buffer overflow",
            "FixedVersion": "1.1.1k",
        }],
        "Misconfigurations": [{
            "ID": "DS002", "Title": "root user", "Severity": "HIGH",
            "Resolution": "USER nonroot",
        }],
    }]
})


def test_parse_trivy_vulns_and_misconfig():
    fs = parse_trivy(TRIVY)
    sevs = {f.rule_id: f.severity for f in fs}
    assert sevs["CVE-2021-1"] == Severity.CRITICAL
    assert sevs["DS002"] == Severity.HIGH
    assert all(f.dimension == Dimension.CONTAINER for f in fs)
    assert all(f.tool == "trivy" for f in fs)


TRIVY_SECRETS = json.dumps({
    "Results": [{
        "Target": "config/app.py",
        "Secrets": [{"RuleID": "aws-access-key-id", "Title": "AWS Access Key",
                     "Severity": "CRITICAL", "StartLine": 14}],
    }]
})


def test_parse_trivy_secrets():
    fs = parse_trivy(TRIVY_SECRETS)
    assert len(fs) == 1
    assert fs[0].severity == Severity.CRITICAL
    assert fs[0].location == "config/app.py:14"
    assert fs[0].rule_id == "aws-access-key-id"
    assert fs[0].dimension == Dimension.CONTAINER


def test_parse_trivy_tolerates_garbage():
    assert parse_trivy("") == []
