"""Dimension nodes (run tools) and the synthesise node (build the Report).

Findings come only from tool wrappers. The LLM writes the executive summary; if it
fails, a deterministic summary is used so a report is always produced."""
from __future__ import annotations

import os
from collections import Counter

from .config import Settings
from .llm import LLMClient
from .observability import RunLogger
from .prioritize import prioritise
from .schemas import (
    Dimension, ExecutiveSummary, Finding, InspectionState, Report, Severity,
    ToolExecution,
)
from .tools import code_quality, container, dependencies, operational, security
from .tools.operational import NOT_ASSESSED


def _run_tools(runners, repo_path, settings, log) -> dict:
    findings: list[Finding] = []
    execs: list[ToolExecution] = []
    for runner in runners:
        fs, ex = runner(repo_path, settings)
        findings.extend(fs)
        execs.append(ex)
        if log:
            log.tool(ex)
    return {"findings": findings, "tools_run": execs}


def _skip(state: InspectionState, dimension: Dimension) -> bool:
    return state.get("depth_plan", {}).get(dimension.value) == "skip"


def make_dimension_nodes(settings: Settings, log: RunLogger | None = None):
    def security_node(state: InspectionState) -> dict:
        if _skip(state, Dimension.SECURITY):
            return {}
        return _run_tools(
            [security.run_semgrep, security.run_detect_secrets, security.run_bandit],
            state["repo_path"], settings, log)

    def code_quality_node(state: InspectionState) -> dict:
        if _skip(state, Dimension.CODE_QUALITY):
            return {}
        fs, ex = code_quality.run_sonar(state["repo_path"], settings)
        if log:
            log.tool(ex)
        return {"findings": fs, "tools_run": [ex]}

    def container_node(state: InspectionState) -> dict:
        if _skip(state, Dimension.CONTAINER):
            return {}
        fs, ex = container.run_trivy(state["repo_path"], settings)
        if log:
            log.tool(ex)
        return {"findings": fs, "tools_run": [ex]}

    def dependencies_node(state: InspectionState) -> dict:
        if _skip(state, Dimension.DEPENDENCIES):
            return {}
        runners = ([dependencies.run_pip_audit] if state.get("repo_language") == "python"
                   else [dependencies.run_npm_audit])
        return _run_tools(runners, state["repo_path"], settings, log)

    def operational_node(state: InspectionState) -> dict:
        if _skip(state, Dimension.OPERATIONAL):
            return {"not_assessed": list(NOT_ASSESSED)}
        out = _run_tools([operational.run_ruff, operational.run_dotenv_linter],
                         state["repo_path"], settings, log)
        out["not_assessed"] = list(NOT_ASSESSED)
        return out

    return {
        "security": security_node, "code_quality": code_quality_node,
        "container": container_node, "dependencies": dependencies_node,
        "operational": operational_node,
    }


_SUMMARY_SYSTEM = (
    "You write a 3-sentence executive summary of a production-readiness audit. You are "
    "given a list of findings ALL produced by analysis tools. Summarise their overall "
    "state and what to fix first. Do NOT invent findings or numbers not in the list. "
    "Reply ONLY as JSON matching the schema."
)


def relativize_location(location: str, repo_path: str) -> str:
    """Rewrite a finding's path to be relative to the repo root, using forward
    slashes. Locations that are not paths under the repo (e.g. 'flask==0.5',
    'lodash@<4.17.12', a bare 'Dockerfile') are returned unchanged."""
    if ":" not in location:
        return location
    head, _, tail = location.rpartition(":")
    if not head:
        return location
    try:
        abs_repo = os.path.abspath(repo_path)
        abs_head = os.path.abspath(head)
        if os.path.commonpath([abs_head, abs_repo]) != abs_repo:
            return location
    except (ValueError, OSError):
        return location  # different drives / bad path
    rel = os.path.relpath(abs_head, abs_repo).replace("\\", "/")
    return f"{rel}:{tail}"


def relativize_findings(findings: list[Finding], repo_path: str) -> list[Finding]:
    for f in findings:
        f.location = relativize_location(f.location, repo_path)
    return findings


def _fallback_summary(findings: list[Finding]) -> str:
    counts = Counter(f.severity for f in findings)
    crit, high = counts[Severity.CRITICAL], counts[Severity.HIGH]
    if not findings:
        return "No findings were produced by the configured tools."
    return (f"{len(findings)} findings ({crit} critical, {high} high). "
            f"Address critical items in critical code paths first.")


def _build_report(repo_path, repo_language, findings, tools_run, not_assessed,
                  summary) -> Report:
    counts = Counter(f.severity for f in findings)
    plan = prioritise(findings)
    skipped = [ex for ex in tools_run if not ex.success]
    return Report(
        executive_summary=summary, repo_path=repo_path, repo_language=repo_language,
        critical_count=counts[Severity.CRITICAL],
        findings_by_severity={s: counts[s] for s in Severity if counts[s]},
        prioritised_remediation_plan=plan,
        estimated_total_effort_hours=round(sum(f.effort_hours for f in findings), 1),
        skipped=skipped, not_assessed=list(not_assessed),
    )


def make_synthesise_node(client: LLMClient, log: RunLogger | None = None):
    def synthesise(state: InspectionState) -> dict:
        findings = relativize_findings(state.get("findings", []), state["repo_path"])
        digest = "\n".join(
            f"- [{f.severity.value}] {f.dimension.value} {f.location}: {f.description}"
            for f in findings[:60]) or "(no findings)"
        try:
            model: ExecutiveSummary = client.generate_json(
                _SUMMARY_SYSTEM, f"Findings:\n{digest}", ExecutiveSummary)
            summary = model.summary
        except Exception:
            summary = _fallback_summary(findings)
        report = _build_report(
            state["repo_path"], state.get("repo_language", "unknown"), findings,
            state.get("tools_run", []), state.get("not_assessed", []), summary)
        if log:
            log.note(f"report built: {report.critical_count} critical, "
                     f"{len(findings)} findings")
        return {"report": report}
    return synthesise
