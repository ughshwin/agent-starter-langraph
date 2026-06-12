"""Subprocess runner that NEVER raises. Every tool wrapper goes through this so a
flaky scanner can't abort the inspection (spec Decision 3)."""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Optional


# Directories that are never the audited project's own code: dependency/vendor
# trees, VCS, build output, caches. Scanning them produces huge volumes of junk
# findings and slows every tool, so every wrapper excludes them.
EXCLUDE_DIRS = [
    "node_modules", ".venv", "venv", "env", ".git", ".hg", ".svn",
    "build", "dist", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".tox", ".eggs", "site-packages", "vendor", ".next",
]

# A regex matching any path that lives under one of EXCLUDE_DIRS (for tools whose
# exclude flag takes a regex, e.g. detect-secrets).
EXCLUDE_REGEX = r"(^|/|\\)(" + "|".join(d.lstrip(".").replace(".", r"\.") for d in
                                        dict.fromkeys(d.strip(".") for d in EXCLUDE_DIRS)) + r")(/|\\|$)"


@dataclass(frozen=True)
class ToolResult:
    ok: bool                 # process ran AND exited 0
    returncode: Optional[int]
    stdout: str
    stderr: str
    duration_ms: int
    error: Optional[str] = None   # set when the process could not run / timed out


def run_cli(cmd: list[str], timeout: float, cwd: Optional[str] = None) -> ToolResult:
    """Run `cmd`, capturing output. Returns a ToolResult; never raises.

    Note: a non-zero exit is `ok=False` but `error=None` (the tool ran, it just
    found problems or failed) — many scanners exit non-zero when they find issues,
    so callers that expect that should check stdout regardless of `ok`.
    A failure to launch or a timeout sets `error`.
    """
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
    except FileNotFoundError as exc:
        ms = int((time.monotonic() - start) * 1000)
        return ToolResult(False, None, "", "", ms, error=f"binary not found: {exc}")
    except subprocess.TimeoutExpired:
        ms = int((time.monotonic() - start) * 1000)
        return ToolResult(False, None, "", "", ms, error=f"timeout after {timeout}s")
    except Exception as exc:  # last-resort guard; runner must never raise
        ms = int((time.monotonic() - start) * 1000)
        return ToolResult(False, None, "", "", ms, error=f"{type(exc).__name__}: {exc}")
    ms = int((time.monotonic() - start) * 1000)
    return ToolResult(
        ok=(proc.returncode == 0), returncode=proc.returncode,
        stdout=proc.stdout or "", stderr=proc.stderr or "", duration_ms=ms,
    )
