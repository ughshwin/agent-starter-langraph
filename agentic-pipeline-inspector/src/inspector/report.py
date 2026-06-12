"""Render a Report as JSON (machine) or markdown (human). The markdown is the
product: summary, counts, the prioritised plan, skipped tools, not-assessed."""
from __future__ import annotations

from .schemas import Report, Severity

_SEV_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]


def render_json(report: Report) -> str:
    return report.model_dump_json(indent=2)


def render_markdown(report: Report) -> str:
    lines = [
        f"# Production-Readiness Report — `{report.repo_path}`",
        "",
        f"**Language:** {report.repo_language}  |  "
        f"**Critical:** {report.critical_count}  |  "
        f"**Est. total effort:** {report.estimated_total_effort_hours}h",
        "",
        "## Executive summary",
        report.executive_summary,
        "",
        "## Findings by severity",
    ]
    for sev in _SEV_ORDER:
        n = report.findings_by_severity.get(sev, 0)
        if n:
            lines.append(f"- **{sev.value}**: {n}")
    lines += ["", "## Prioritised remediation plan", ""]
    if not report.prioritised_remediation_plan:
        lines.append("_No findings._")
    for step in report.prioritised_remediation_plan:
        f = step.finding
        rule = f" ({f.rule_id})" if f.rule_id else ""
        lines += [
            f"### #{step.rank} — [{f.severity.value}] {f.location}{rule}",
            f"- **Dimension:** {f.dimension.value}  ·  **Tool:** {f.tool}  ·  "
            f"**Effort:** ~{f.effort_hours}h  ·  **Risk:** {step.risk_score:.1f}",
            f"- **Issue:** {f.description}",
            f"- **Fix:** {f.recommendation or '(see tool output)'}",
            f"- _{step.rationale}_",
            "",
        ]
    if report.skipped:
        lines += ["## Tools that failed / were skipped", ""]
        for ex in report.skipped:
            lines.append(f"- `{ex.tool_name}`: {ex.error or 'no output'}")
        lines.append("")
    if report.not_assessed:
        lines += ["## Not assessed (no dedicated tool)", ""]
        for item in report.not_assessed:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines)
