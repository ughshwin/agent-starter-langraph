#!/usr/bin/env bash
# Install every scanner the inspector orchestrates, on Linux (tested target: A40 VM).
# Idempotent-ish: re-running is safe. Requires sudo for the binary installs.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${BIN_DIR:-/usr/local/bin}"

echo "==> Python scanners (semgrep, detect-secrets, bandit, pip-audit, ruff) + deps"
python3 -m pip install --upgrade pip
python3 -m pip install -r "$HERE/requirements.txt"

echo "==> trivy (container/filesystem scanner)"
if ! command -v trivy >/dev/null 2>&1; then
  curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh \
    | sudo sh -s -- -b "$BIN_DIR"
fi
trivy --version

echo "==> dotenv-linter (config linter)"
if ! command -v dotenv-linter >/dev/null 2>&1; then
  curl -sSfL https://raw.githubusercontent.com/dotenv-linter/dotenv-linter/master/install.sh \
    | sudo sh -s -- -b "$BIN_DIR"
fi
dotenv-linter --version

echo "==> sonar-scanner CLI"
if ! command -v sonar-scanner >/dev/null 2>&1; then
  SCANNER_VER="${SCANNER_VER:-6.2.1.4610}"
  TMP="$(mktemp -d)"
  curl -sSLo "$TMP/scanner.zip" \
    "https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-${SCANNER_VER}-linux-x64.zip"
  sudo unzip -q -o "$TMP/scanner.zip" -d /opt
  sudo ln -sf "/opt/sonar-scanner-${SCANNER_VER}-linux-x64/bin/sonar-scanner" "$BIN_DIR/sonar-scanner"
  rm -rf "$TMP"
fi
sonar-scanner --version || true

echo "==> Ollama model"
if command -v ollama >/dev/null 2>&1; then
  ollama pull "${INSPECTOR_MODEL:-qwen2.5:3b}"
  # On a 48GB A40 a larger model gives better summaries; uncomment to also pull:
  # ollama pull qwen2.5:7b
else
  echo "    ollama not found — install from https://ollama.com and pull qwen2.5:3b"
fi

echo
echo "All scanners installed. SonarQube server: see docker-compose.sonar.yml"
echo "Then export SONAR_URL / SONAR_TOKEN / SONAR_PROJECT_KEY before running."
