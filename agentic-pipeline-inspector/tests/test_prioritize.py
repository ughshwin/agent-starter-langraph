from inspector.prioritize import path_criticality, prioritise
from inspector.schemas import Dimension, Finding, Severity


def _f(sev, loc, effort, tool="t"):
    return Finding(dimension=Dimension.SECURITY, severity=sev, location=loc,
                   description="d", recommendation="r", effort_hours=effort, tool=tool)


def test_path_criticality_boosts_auth_files():
    assert path_criticality("src/auth/login.py:1") > path_criticality("src/zzz.py:1")


def test_prioritise_orders_high_risk_low_effort_first():
    findings = [
        _f(Severity.LOW, "zzz.py:1", 1.0),
        _f(Severity.CRITICAL, "auth/login.py:1", 1.0),
        _f(Severity.CRITICAL, "zzz.py:2", 8.0),
    ]
    plan = prioritise(findings)
    assert plan[0].rank == 1
    assert plan[0].finding.location == "auth/login.py:1"   # critical + critical path
    assert [s.rank for s in plan] == [1, 2, 3]


def test_prioritise_empty():
    assert prioritise([]) == []
