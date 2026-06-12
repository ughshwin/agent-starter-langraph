"""Settings: model, per-tool timeout, SonarQube connection, reliability tunables."""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL = "qwen2.5:3b"


@dataclass(frozen=True)
class Settings:
    model: str = DEFAULT_MODEL
    tool_timeout: float = 300.0          # seconds per scanner subprocess
    llm_timeout: float = 240.0
    llm_num_predict: int = 700
    validation_retries: int = 2

    # SonarQube (read from env so tokens never live in code)
    sonar_url: str = os.environ.get("SONAR_URL", "http://localhost:9000")
    sonar_token: str = os.environ.get("SONAR_TOKEN", "")
    sonar_project_key: str = os.environ.get("SONAR_PROJECT_KEY", "inspector-target")

    verbose: bool = True

    def validate(self) -> None:
        if self.tool_timeout <= 0:
            raise ValueError(f"tool_timeout must be > 0, got {self.tool_timeout}")
        if self.llm_timeout <= 0:
            raise ValueError(f"llm_timeout must be > 0, got {self.llm_timeout}")
