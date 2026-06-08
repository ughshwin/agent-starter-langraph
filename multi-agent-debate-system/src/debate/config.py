"""Settings: per-role models and the reliability tunables.

Defaults encode the design decision — three different model families, with the
single reasoning model reserved for the Judge.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# One model per role. Different families on the two sides make genuine
# disagreement more likely (brief Decision 2); the reasoning model is the Judge's.
DEFAULT_PROPOSER_MODEL = "llama3.1:latest"
DEFAULT_OPPOSER_MODEL = "qwen2.5:7b"
DEFAULT_JUDGE_MODEL = "qwen3:8b"  # thinking model

HISTORY_MODES = ("hybrid", "full", "last")


@dataclass(frozen=True)
class Settings:
    proposer_model: str = DEFAULT_PROPOSER_MODEL
    opposer_model: str = DEFAULT_OPPOSER_MODEL
    judge_model: str = DEFAULT_JUDGE_MODEL

    max_rounds: int = 3  # brief: max 3, min 2
    history_mode: str = "hybrid"

    # Whether the Judge uses thinking mode. Turn OFF when the judge model is not a
    # thinking model (e.g. qwen2.5) — avoids a wasted failed call per Judge turn.
    enable_thinking: bool = True

    # Per-call generation caps. The thinking Judge needs room for its reasoning
    # trace plus the verdict; advocates only need a paragraph + rebuttal points.
    advocate_num_predict: int = 900
    judge_observe_num_predict: int = 1200
    judge_verdict_num_predict: int = 3000

    # Per-LLM-call timeout (seconds). The only thing that stops a hung generation
    # on a CPU/GPU split. The Judge (thinking) gets a longer budget.
    advocate_timeout: float = 240.0
    judge_timeout: float = 420.0

    # How many times to re-ask a model whose output fails schema validation,
    # feeding the error back each time before giving up.
    validation_retries: int = 2

    verbose: bool = True

    def models(self) -> dict[str, str]:
        return {
            "proposer": self.proposer_model,
            "opposer": self.opposer_model,
            "judge": self.judge_model,
        }

    def with_single_model(self, model: str) -> "Settings":
        """Collapse all three roles onto one model (speed over heterogeneity)."""
        return replace(
            self, proposer_model=model, opposer_model=model, judge_model=model
        )

    def validate(self) -> None:
        if self.history_mode not in HISTORY_MODES:
            raise ValueError(
                f"history_mode must be one of {HISTORY_MODES}, got {self.history_mode!r}"
            )
        if not (2 <= self.max_rounds <= 3):
            raise ValueError(f"max_rounds must be 2 or 3, got {self.max_rounds}")
