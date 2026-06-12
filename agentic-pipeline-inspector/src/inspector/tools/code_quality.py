"""Code quality: SonarQube. `sonar-scanner` runs the analysis against a running
Sonar server; we then read the issues via the web API. Findings come only from
Sonar. If the server is unreachable, the dimension degrades (handled by caller)."""
from __future__ import annotations

import re
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


def _default_fetch(settings: Settings) -> dict:
    """Read issues from the Sonar web API. Imported lazily so tests need no network."""
    import requests
    resp = requests.get(
        f"{settings.sonar_url}/api/issues/search",
        params={"componentKeys": settings.sonar_project_key, "ps": 500},
        auth=(settings.sonar_token, "") if settings.sonar_token else None,
        timeout=settings.llm_timeout,
    )
    resp.raise_for_status()
    return resp.json()


def run_sonar(repo_path: str, settings: Settings,
              fetch: Callable[[Settings], dict] = _default_fetch):
    """Trigger sonar-scanner (best-effort), then read issues from the API."""
    scan = run_cli(
        ["sonar-scanner",
         f"-Dsonar.projectKey={settings.sonar_project_key}",
         "-Dsonar.sources=.",
         f"-Dsonar.host.url={settings.sonar_url}",
         f"-Dsonar.token={settings.sonar_token}"],
        timeout=settings.tool_timeout, cwd=repo_path,
    )
    try:
        data = fetch(settings)
    except Exception as exc:
        exec_ = ToolExecution(tool_name="sonarqube", input={"path": repo_path},
                              success=False, duration_ms=scan.duration_ms,
                              error=f"sonar API unreachable: {type(exc).__name__}: {exc}")
        return [], exec_
    exec_ = ToolExecution(tool_name="sonarqube", input={"path": repo_path},
                          success=True, duration_ms=scan.duration_ms, error=None)
    return parse_sonar_issues(data), exec_
