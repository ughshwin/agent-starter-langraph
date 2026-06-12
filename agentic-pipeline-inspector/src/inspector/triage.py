"""Triage node: detect cheap repo signals (deterministic), then let the LLM pick
per-dimension investigation depth (control only — never produces findings)."""
from __future__ import annotations

import os

from .config import Settings
from .llm import InspectorLLMError, LLMClient
from .schemas import DepthPlan, InspectionState

_DEPTHS = {"deep", "standard", "skip"}


def detect_language(repo_path: str) -> str:
    py = js = 0
    for root, _dirs, files in os.walk(repo_path):
        if any(skip in root for skip in (".git", "node_modules", ".venv")):
            continue
        for f in files:
            if f.endswith(".py"):
                py += 1
            elif f.endswith((".js", ".ts", ".jsx", ".tsx")):
                js += 1
            if f == "package.json":
                js += 5
    if py == 0 and js == 0:
        return "unknown"
    return "python" if py >= js else "javascript"


def detect_signals(repo_path: str) -> dict:
    entries = set()
    for root, _dirs, files in os.walk(repo_path):
        if ".git" in root:
            continue
        for f in files:
            entries.add(f.lower())
    return {
        "language": detect_language(repo_path),
        "has_dockerfile": "dockerfile" in entries
        or any(e.endswith("docker-compose.yml") or e == "docker-compose.yml"
               for e in entries),
        "has_coverage": any(e in entries for e in ("coverage.xml", ".coverage")),
        "has_env": any(e == ".env" or e.endswith(".env") for e in entries),
    }


_TRIAGE_SYSTEM = (
    "You plan a production-readiness audit. Given repo signals, decide how deeply to "
    "investigate each of five dimensions. Reply ONLY as JSON matching the schema, each "
    "value one of: deep, standard, skip. You do NOT analyse code — you only choose "
    "depth. Skip 'container' if there is no Dockerfile. Prefer 'deep' code_quality when "
    "there is no coverage. Never skip security."
)


def _fallback_plan() -> dict[str, str]:
    return {d: "standard" for d in
            ("security", "code_quality", "container", "dependencies", "operational")}


def make_triage_node(client: LLMClient, settings: Settings, log=None):
    def triage(state: InspectionState) -> dict:
        signals = detect_signals(state["repo_path"])
        user = f"Repo signals: {signals}. Choose investigation depth per dimension."
        try:
            plan_model: DepthPlan = client.generate_json(_TRIAGE_SYSTEM, user, DepthPlan)
            plan = {k: (v if v in _DEPTHS else "standard")
                    for k, v in plan_model.model_dump().items()}
        except InspectorLLMError:
            plan = _fallback_plan()
        if not signals["has_dockerfile"]:
            plan["container"] = "skip"
        if log:
            log.decision("triage", plan, f"signals={signals}")
        return {"repo_language": signals["language"], "depth_plan": plan}
    return triage
