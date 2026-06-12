import json

from inspector.schemas import Dimension, Severity
from inspector.tools.dependencies import parse_npm_audit, parse_pip_audit

PIP = json.dumps({
    "dependencies": [{
        "name": "flask", "version": "0.5",
        "vulns": [{"id": "PYSEC-2019-1", "fix_versions": ["1.0"],
                   "description": "XSS in flask"}],
    }]
})

NPM = json.dumps({
    "vulnerabilities": {
        "lodash": {"severity": "high", "via": [{"title": "Prototype pollution",
                   "url": "https://x", "source": 1065}], "range": "<4.17.12"}
    }
})


def test_parse_pip_audit():
    fs = parse_pip_audit(PIP)
    assert fs[0].dimension == Dimension.DEPENDENCIES
    assert fs[0].rule_id == "PYSEC-2019-1"
    assert "flask" in fs[0].location
    assert fs[0].tool == "pip-audit"


def test_parse_npm_audit_maps_high():
    fs = parse_npm_audit(NPM)
    assert fs[0].severity == Severity.HIGH
    assert "lodash" in fs[0].location
    assert fs[0].tool == "npm-audit"


def test_dependency_parsers_tolerate_garbage():
    assert parse_pip_audit("") == []
    assert parse_npm_audit("nope") == []
