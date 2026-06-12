import json

from inspector.schemas import Dimension
from inspector.tools.operational import NOT_ASSESSED, parse_dotenv_linter, parse_ruff

RUFF = json.dumps([
    {"code": "E722", "message": "do not use bare except", "filename": "a.py",
     "location": {"row": 3, "column": 1}, "url": "https://x"},
])


def test_parse_ruff():
    fs = parse_ruff(RUFF)
    assert fs[0].dimension == Dimension.OPERATIONAL
    assert fs[0].location == "a.py:3"
    assert fs[0].rule_id == "E722"
    assert fs[0].tool == "ruff"


def test_parse_dotenv_linter_text():
    out = ".env:2 LowercaseKey: The api_key key should be in uppercase"
    fs = parse_dotenv_linter(out)
    assert fs[0].dimension == Dimension.OPERATIONAL
    assert fs[0].location == ".env:2"
    assert fs[0].tool == "dotenv-linter"


def test_not_assessed_is_declared():
    assert any("shutdown" in x.lower() for x in NOT_ASSESSED)


def test_operational_parsers_tolerate_garbage():
    assert parse_ruff("") == []
    assert parse_dotenv_linter("") == []
