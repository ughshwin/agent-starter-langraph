from inspector.config import Settings
from main import build_parser, run_inspection


def test_parser_defaults():
    args = build_parser().parse_args(["inspect", "somepath"])
    assert args.repo_path == "somepath"
    assert args.format == "md"


def test_run_inspection_returns_rendered_report(monkeypatch, tmp_path, fake_llm):
    (tmp_path / "main.py").write_text("x=1\n")
    import main as main_mod
    from inspector.schemas import Report

    class FakeGraph:
        def invoke(self, state):
            state = dict(state)
            state["report"] = Report(
                executive_summary="ok", repo_path=str(tmp_path),
                repo_language="python", critical_count=0, findings_by_severity={},
                prioritised_remediation_plan=[], estimated_total_effort_hours=0.0,
                skipped=[], not_assessed=[])
            return state

    monkeypatch.setattr(main_mod, "build_graph", lambda c, s, log=None: FakeGraph())
    out = run_inspection(str(tmp_path), fmt="md", settings=Settings(verbose=False),
                         client=fake_llm)
    assert "Executive summary" in out
