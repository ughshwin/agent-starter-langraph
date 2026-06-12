from inspector.triage import detect_language, detect_signals


def test_detect_language_python(tmp_path):
    (tmp_path / "main.py").write_text("print(1)")
    assert detect_language(str(tmp_path)) == "python"


def test_detect_language_javascript(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert detect_language(str(tmp_path)) == "javascript"


def test_detect_language_unknown(tmp_path):
    (tmp_path / "readme.txt").write_text("hi")
    assert detect_language(str(tmp_path)) == "unknown"


def test_detect_signals_reports_dockerfile(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python")
    (tmp_path / "main.py").write_text("x=1")
    sig = detect_signals(str(tmp_path))
    assert sig["has_dockerfile"] is True
    assert sig["language"] == "python"
