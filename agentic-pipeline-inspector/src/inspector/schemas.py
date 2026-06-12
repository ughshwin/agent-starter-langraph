"""Data shapes for an inspection.

Two layers: wire schemas the LLM fills (triage/summary) and the audit data
(`Finding`, `Report`) which comes only from tools. `InspectionState` is the
LangGraph working memory; `findings`/`tools_run` use `add` reducers so each node
returns only its slice and the graph accumulates the whole audit.
"""
from __future__ import annotations

from enum import Enum
from operator import add
from typing import Annotated, Optional, TypedDict

from pydantic import BaseModel, Field


class Dimension(str, Enum):
    SECURITY = "security"
    CODE_QUALITY = "code_quality"
    CONTAINER = "container"
    DEPENDENCIES = "dependencies"
    OPERATIONAL = "operational"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_WEIGHT = {
    Severity.CRITICAL: 8.0,
    Severity.HIGH: 4.0,
    Severity.MEDIUM: 2.0,
    Severity.LOW: 1.0,
}

# Fixed fallback effort estimate (hours) when a tool does not report effort.
# A constant table — NOT repo analysis.
DEFAULT_EFFORT_HOURS = {
    Severity.CRITICAL: 4.0,
    Severity.HIGH: 2.0,
    Severity.MEDIUM: 1.0,
    Severity.LOW: 0.5,
}


class Finding(BaseModel):
    dimension: Dimension
    severity: Severity
    location: str            # "file:line" from the tool
    description: str         # from the tool
    recommendation: str      # from the tool, or "" if none provided
    effort_hours: float
    tool: str                # provenance
    rule_id: Optional[str] = None


class ToolExecution(BaseModel):
    tool_name: str
    input: dict
    success: bool
    duration_ms: int
    error: Optional[str] = None


class RemediationStep(BaseModel):
    rank: int
    finding: Finding
    risk_score: float
    rationale: str


class Report(BaseModel):
    executive_summary: str
    repo_path: str
    repo_language: str
    critical_count: int
    findings_by_severity: dict[Severity, int]
    prioritised_remediation_plan: list[RemediationStep]
    estimated_total_effort_hours: float
    skipped: list[ToolExecution]
    not_assessed: list[str] = Field(default_factory=list)


# --- LLM wire schemas (the ONLY things the model fills) ----------------------

class DepthPlan(BaseModel):
    """Triage output: how deeply to investigate each dimension. Control only."""
    security: str = Field(description="one of: deep | standard | skip")
    code_quality: str = Field(description="one of: deep | standard | skip")
    container: str = Field(description="one of: deep | standard | skip")
    dependencies: str = Field(description="one of: deep | standard | skip")
    operational: str = Field(description="one of: deep | standard | skip")


class ExecutiveSummary(BaseModel):
    """Synthesise output: prose only, over findings the tools produced."""
    summary: str = Field(
        description="At most 3 sentences. What is the overall production-readiness "
        "state and what should be fixed first. Do not invent findings."
    )


class InspectionState(TypedDict):
    repo_path: str
    repo_language: str
    depth_plan: dict[str, str]
    findings: Annotated[list[Finding], add]
    tools_run: Annotated[list[ToolExecution], add]
    not_assessed: Annotated[list[str], add]
    report: Optional[Report]
