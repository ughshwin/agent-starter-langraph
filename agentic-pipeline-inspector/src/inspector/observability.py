"""Structured JSON run logging (spec Decision 6). One line per tool execution and
per LLM decision, so any report can be traced to exactly what was investigated."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

from .schemas import ToolExecution


class RunLogger:
    def __init__(self, path: Optional[Path] = None, verbose: bool = True):
        self._path = Path(path) if path else None
        self._verbose = verbose
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("")  # truncate per run

    def _emit(self, record: dict) -> None:
        record["ts"] = time.time()
        line = json.dumps(record, default=str)
        if self._path:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        if self._verbose:
            print(line, file=sys.stderr, flush=True)

    def tool(self, execution: ToolExecution) -> None:
        rec = {"event": "tool"}
        rec.update(execution.model_dump())
        self._emit(rec)

    def decision(self, node: str, choice, reason: str) -> None:
        self._emit({"event": "decision", "node": node, "choice": choice,
                    "reason": reason})

    def note(self, message: str) -> None:
        self._emit({"event": "note", "message": message})
