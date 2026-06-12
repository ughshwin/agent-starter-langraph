"""Code quality: SonarQube. `sonar-scanner` runs the analysis against a running
Sonar server; we then read the issues via the web API. Findings come only from
Sonar. If the server is unreachable, the dimension degrades (handled by caller)."""
from __future__ import annotations

import os
import re
import time
from typing import Callable, Optional

from ..config import Settings
from ..schemas import Dimension, Finding, Severity, ToolExecution
from .base import run_cli

_SONAR_SEVERITY = {
    "BLOCKER": Severity.CRITICAL, "CRITICAL": Severity.HIGH,
    "MAJOR": Severity.MEDIUM, "MINOR": Severity.LOW, "INFO": Severity.LOW,
}


def sonar_to_severity(s: str) -> Severity:
    return _SONAR_SEVERITY.get((s or "").upper(), Severity.LOW)


def _effort_hours(effort: Optional[str]) -> float:
    """Sonar effort like '10min', '1h', '1h30min' → hours. Falls back to 0.5."""
    if not effort:
        return 0.5
    h = re.search(r"(\d+)h", effort)
    m = re.search(r"(\d+)min", effort)
    hours = (int(h.group(1)) if h else 0) + (int(m.group(1)) / 60 if m else 0)
    return hours or 0.5


def parse_sonar_issues(data: dict) -> list[Finding]:
    out = []
    for i in data.get("issues", []):
        sev = sonar_to_severity(i.get("severity", ""))
        component = i.get("component", "?")
        path = component.split(":", 1)[-1]  # strip "projectKey:" prefix
        loc = f"{path}:{i.get('line', 0)}"
        out.append(Finding(
            dimension=Dimension.CODE_QUALITY, severity=sev, location=loc,
            description=i.get("message", ""), recommendation="",
            effort_hours=_effort_hours(i.get("effort")), tool="sonarqube",
            rule_id=i.get("rule"),
        ))
    return out


def _ce_task_id(repo_path: str) -> Optional[str]:
    """sonar-scanner writes the compute-engine task id to report-task.txt."""
    report = os.path.join(repo_path, ".scannerwork", "report-task.txt")
    try:
        for line in open(report, encoding="utf-8"):
            if line.startswith("ceTaskId="):
                return line.strip().split("=", 1)[1]
    except OSError:
        return None
    return None


def _auth(settings: Settings):
    return (settings.sonar_token, "") if settings.sonar_token else None


def _wait_for_analysis(settings: Settings, ce_task_id: str, deadline: float) -> bool:
    """Poll the CE task until the server finishes processing the analysis.

    Returns True on SUCCESS. Sonar processes uploads asynchronously, so issues are
    not queryable until the task completes — querying before this returns stale data."""
    import requests
    url = f"{settings.sonar_url}/api/ce/task"
    while time.monotonic() < deadline:
        resp = requests.get(url, params={"id": ce_task_id}, auth=_auth(settings),
                            timeout=30)
        resp.raise_for_status()
        status = resp.json().get("task", {}).get("status", "")
        if status == "SUCCESS":
            return True
        if status in ("FAILED", "CANCELED"):
            return False
        time.sleep(2)
    return False


def _default_fetch(settings: Settings) -> dict:
    """Read issues from the Sonar web API. Imported lazily so tests need no network."""
    import requests
    resp = requests.get(
        f"{settings.sonar_url}/api/issues/search",
        params={"componentKeys": settings.sonar_project_key, "ps": 500,
                "resolved": "false"},
        auth=_auth(settings), timeout=settings.llm_timeout,
    )
    resp.raise_for_status()
    return resp.json()


def run_sonar(repo_path: str, settings: Settings,
              fetch: Callable[[Settings], dict] = _default_fetch):
    """Run sonar-scanner, wait for the server to finish analysis, then read issues.

    Any failure (scanner error, server unreachable, analysis timeout) degrades to a
    noted skip — never aborts the inspection."""
    scan = run_cli(
        ["sonar-scanner",
         f"-Dsonar.projectKey={settings.sonar_project_key}",
         "-Dsonar.sources=.",
         f"-Dsonar.host.url={settings.sonar_url}",
         f"-Dsonar.token={settings.sonar_token}"],
        timeout=settings.tool_timeout, cwd=repo_path,
    )

    def _skip(msg: str):
        return [], ToolExecution(tool_name="sonarqube", input={"path": repo_path},
                                 success=False, duration_ms=scan.duration_ms, error=msg)

    if scan.error:
        return _skip(f"sonar-scanner failed: {scan.error}")

    try:
        ce_id = _ce_task_id(repo_path)
        if ce_id is not None:
            deadline = time.monotonic() + settings.tool_timeout
            if not _wait_for_analysis(settings, ce_id, deadline):
                return _skip("sonar analysis did not complete (CE task not SUCCESS)")
        data = fetch(settings)
    except Exception as exc:
        return _skip(f"sonar API error: {type(exc).__name__}: {exc}")

    exec_ = ToolExecution(tool_name="sonarqube", input={"path": repo_path},
                          success=True, duration_ms=scan.duration_ms, error=None)
    return parse_sonar_issues(data), exec_
