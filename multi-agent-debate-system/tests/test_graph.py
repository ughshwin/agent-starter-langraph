"""Drive the entire LangGraph with a FakeLLM — no Ollama, no models loaded.

Verifies the coordination/state machine the brief actually targets: correct number
of rounds, round counter advancing, list accumulation, termination, and that a
Verdict comes out the end. Also unit-tests the routing policy directly.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from debate.config import Settings
from debate.graph import build_graph, route_round
from debate.runner import initial_state, run_debate
from debate.schemas import ArgumentPayload, Verdict


class FakeLLM:
    """Returns valid schema instances; records every call for assertions."""

    def __init__(self):
        self.json_calls = []
        self.text_calls = []

    def generate_json(self, model, system, user, schema, **kw):
        self.json_calls.append((model, schema.__name__))
        if schema is ArgumentPayload:
            role = "PRO" if "PROPOSER" in system else "CON"
            return ArgumentPayload(argument=f"{role} via {model}", rebuttals_to=["pt"])
        if schema is Verdict:
            return Verdict(
                recommendation="conditional yes",
                confidence=0.6,
                key_factors=["a"],
                conditions=["holds if X"],
                dissenting_considerations=["y"],
            )
        raise AssertionError(f"unexpected schema {schema}")

    def generate_text(self, model, system, user, **kw):
        self.text_calls.append(model)
        return "address operational complexity next round"


def test_route_round_loops_then_finishes():
    assert route_round({"round": 2, "max_rounds": 3}) == "proposer"
    assert route_round({"round": 3, "max_rounds": 3}) == "proposer"
    assert route_round({"round": 4, "max_rounds": 3}) == "judge_verdict"
    # 2-round debate
    assert route_round({"round": 3, "max_rounds": 2}) == "judge_verdict"


def test_full_three_round_debate():
    settings = Settings(verbose=False, max_rounds=3)
    fake = FakeLLM()
    final = run_debate("in-house vs Auth0?", settings, client=fake)

    assert len(final["proposer_arguments"]) == 3
    assert len(final["opposer_arguments"]) == 3
    assert len(final["judge_observations"]) == 3  # observed after each round
    assert final["round"] == 4  # incremented past max_rounds to terminate
    assert isinstance(final["final_verdict"], Verdict)
    # one verdict json call, plus 6 advocate json calls
    assert ("qwen3:8b", "Verdict") in fake.json_calls
    assert sum(1 for _, s in fake.json_calls if s == "ArgumentPayload") == 6


def test_two_round_debate_terminates_early():
    settings = Settings(verbose=False, max_rounds=2)
    final = run_debate("monolith vs microservices?", settings, client=FakeLLM())
    assert len(final["proposer_arguments"]) == 2
    assert isinstance(final["final_verdict"], Verdict)


def test_heterogeneous_models_used_per_role():
    settings = Settings(verbose=False, max_rounds=2)
    fake = FakeLLM()
    run_debate("q?", settings, client=fake)
    models_used = {m for m, _ in fake.json_calls} | set(fake.text_calls)
    assert settings.proposer_model in models_used
    assert settings.opposer_model in models_used
    assert settings.judge_model in models_used


def test_initial_state_shape():
    s = initial_state("q", Settings(max_rounds=3, history_mode="full"))
    assert s["round"] == 1 and s["max_rounds"] == 3 and s["history_mode"] == "full"
    assert s["final_verdict"] is None
