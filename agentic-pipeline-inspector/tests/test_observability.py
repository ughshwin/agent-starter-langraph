import json

from inspector.observability import RunLogger
from inspector.schemas import ToolExecution


def test_logs_tool_and_decision_as_json_lines(tmp_path):
    path = tmp_path / "run.jsonl"
    log = RunLogger(path, verbose=False)
    log.tool(ToolExecution(tool_name="bandit", input={"p": "."}, success=True,
                           duration_ms=12, error=None))
    log.decision("triage", {"security": "deep"}, "no tests found")
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    rec0 = json.loads(lines[0])
    assert rec0["event"] == "tool" and rec0["tool_name"] == "bandit"
    rec1 = json.loads(lines[1])
    assert rec1["event"] == "decision" and rec1["node"] == "triage"
