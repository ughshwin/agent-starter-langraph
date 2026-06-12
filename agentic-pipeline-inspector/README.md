# Agentic Pipeline Inspector

Point-in-time production-readiness auditor for Python/JavaScript repos.
See `docs/superpowers/specs/2026-06-12-agentic-pipeline-inspector-design.md`.

## Setup
See spec §10. Requires: pip deps (`pip install -r requirements.txt`), trivy,
dotenv-linter, a SonarQube Community server (Docker) + sonar-scanner, and Ollama
with `qwen2.5:3b`.

## Usage
    python main.py inspect <repo_path> [--format json|md] [--out report.md]
