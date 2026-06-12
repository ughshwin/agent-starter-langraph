import sys

from inspector.tools.base import ToolResult, run_cli


def test_run_cli_captures_stdout():
    r = run_cli([sys.executable, "-c", "print('hi')"], timeout=30)
    assert isinstance(r, ToolResult)
    assert r.ok
    assert "hi" in r.stdout
    assert r.duration_ms >= 0


def test_run_cli_nonzero_exit_is_not_ok_but_does_not_raise():
    r = run_cli([sys.executable, "-c", "import sys; sys.exit(2)"], timeout=30)
    assert r.ok is False
    assert r.returncode == 2


def test_run_cli_missing_binary_returns_error_not_raise():
    r = run_cli(["this_binary_does_not_exist_xyz"], timeout=30)
    assert r.ok is False
    assert r.error is not None


def test_run_cli_timeout_returns_error_not_raise():
    r = run_cli([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)
    assert r.ok is False
    assert "timeout" in (r.error or "").lower()
