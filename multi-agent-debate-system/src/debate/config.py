"""Settings: per-role models and the reliability tunables.

Defaults encode the design decision — three different model families, with the
single reasoning model reserved for the Judge.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# One reasoning model per role, each from a DIFFERENT lab — no two share a provider.
# Three different labs' training makes genuine disagreement far more likely than one
# family talking to itself, and every role reasons (thinks) before it speaks.
DEFAULT_DEFENCE_MODEL = "gpt-oss:20b"        # OpenAI   — Defence counsel
DEFAULT_PROSECUTION_MODEL = "deepseek-r1:14b"  # DeepSeek — Prosecution counsel
DEFAULT_JUDGE_MODEL = "qwen3:32b"            # Alibaba  — the bench (strongest model)

HISTORY_MODES = ("hybrid", "full", "last")

# Upper bound on rounds. The brief capped this at 3; we lift it for deep internal
# debate. Kept finite so a bad --rounds value can't run forever.
MAX_ROUNDS_LIMIT = 20


@dataclass(frozen=True)
class Settings:
    defence_model: str = DEFAULT_DEFENCE_MODEL
    prosecution_model: str = DEFAULT_PROSECUTION_MODEL
    judge_model: str = DEFAULT_JUDGE_MODEL

    max_rounds: int = 6  # cross-examination rounds; min 2, max MAX_ROUNDS_LIMIT
    history_mode: str = "hybrid"

    # Whether the Judge uses thinking mode. Keep ON for reasoning judges (qwen3,
    # deepseek-r1, gpt-oss); turn OFF only for a non-thinking judge model.
    enable_thinking: bool = True

    # Whether the two ADVOCATES also reason before answering. ON by default now that
    # every role is a reasoning model — this is what makes the debate "deep" rather
    # than three models pattern-matching. Set OFF for plain models to save tokens.
    advocate_think: bool = True

    # Per-call generation caps. NOTE: with reasoning models the hidden thinking trace
    # counts against num_predict, so these are deliberately large — a small cap would
    # truncate the model mid-thought and leave no room for the JSON answer.
    advocate_num_predict: int = 4000
    judge_direct_num_predict: int = 3000
    judge_verdict_num_predict: int = 6000

    # Per-LLM-call timeout (seconds). The only thing that stops a hung generation.
    # Reasoning models think for a while, so the budgets are generous.
    advocate_timeout: float = 600.0
    judge_timeout: float = 900.0

    # How many times to re-ask a model whose output fails schema validation,
    # feeding the error back each time before giving up.
    validation_retries: int = 2

    verbose: bool = True

    def models(self) -> dict[str, str]:
        return {
            "defence": self.defence_model,
            "prosecution": self.prosecution_model,
            "judge": self.judge_model,
        }

    def with_single_model(self, model: str) -> "Settings":
        """Collapse all three roles onto one model (speed over heterogeneity)."""
        return replace(
            self, defence_model=model, prosecution_model=model, judge_model=model
        )

    def validate(self) -> None:
        if self.history_mode not in HISTORY_MODES:
            raise ValueError(
                f"history_mode must be one of {HISTORY_MODES}, got {self.history_mode!r}"
            )
        if not (2 <= self.max_rounds <= MAX_ROUNDS_LIMIT):
            raise ValueError(
                f"max_rounds must be between 2 and {MAX_ROUNDS_LIMIT}, "
                f"got {self.max_rounds}"
            )
