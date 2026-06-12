"""End-to-end graph run with a FakeLLM and stubbed tool runners — no real scanners
or Ollama needed. Proves triage → dimensions → synthesise produces a report."""
import inspector.nodes as nodes
from inspector.config import Settings
from inspector.graph import build_graph
from inspector.schemas import Dimension, Finding, Severity, ToolExecution


def _ok_exec(name):
    return ToolExecution(tool_name=name, input={}, success=True, duration_ms=1, error=None)


def _stub_with_finding(name):
    def run(repo_path, settings):
        f = Finding(dimension=Dimension.SECURITY, severity=Severity.HIGH,
                    location="main.py:2", description="eval", recommendation="x",
                    effort_hours=1.0, tool=name)
        return [f], _ok_exec(name)
    return run


def _stub_empty(name):
    def run(repo_path, settings):
        return [], _ok_exec(name)
    return run


def test_graph_runs_end_to_end_with_fake_llm(monkeypatch, tmp_path, fake_llm):
    (tmp_path / "main.py").write_text("import os\nx=eval('1')\n")

    monkeypatch.setattr(nodes.security, "run_semgrep", _stub_with_finding("semgrep"))
    monkeypatch.setattr(nodes.security, "run_detect_secrets", _stub_empty("detect-secrets"))
    monkeypatch.setattr(nodes.security, "run_bandit", _stub_with_finding("bandit"))
    monkeypatch.setattr(nodes.dependencies, "run_pip_audit", _stub_empty("pip-audit"))
    monkeypatch.setattr(nodes.operational, "run_ruff", _stub_empty("ruff"))
    monkeypatch.setattr(nodes.operational, "run_dotenv_linter", _stub_empty("dotenv-linter"))
    monkeypatch.setattr(nodes.code_quality, "run_sonar", _stub_empty("sonarqube"))
    monkeypatch.setattr(nodes.container, "run_trivy", _stub_empty("trivy"))

    graph = build_graph(fake_llm, Settings(verbose=False))
    final = graph.invoke({
        "repo_path": str(tmp_path), "repo_language": "", "depth_plan": {},
        "findings": [], "tools_run": [], "not_assessed": [], "report": None,
    })
    assert final["report"] is not None
    assert final["report"].repo_language == "python"
    assert len(final["report"].prioritised_remediation_plan) >= 1
