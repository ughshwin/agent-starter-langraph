"""Drive the entire courtroom LangGraph with a FakeLLM — no Ollama, no models.

Verifies the coordination/state machine: the phase order (opening →
cross-examination → closing → opinion), the correct number of examination rounds,
the round counter advancing, record accumulation, termination, and that a Verdict
comes out the end. Also unit-tests the routing policy directly.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from debate.config import Settings
from debate.graph import build_graph, route_examination
from debate.runner import initial_state, run_debate
from debate.schemas import DebateFraming, ExaminationTurn, Statement, Verdict


class FakeLLM:
    """Returns valid schema instances; records every call for assertions."""

    def __init__(self):
        self.json_calls = []
        self.text_calls = []

    def generate_json(self, model, system, user, schema, **kw):
        self.json_calls.append((model, schema.__name__))
        if schema is DebateFraming:
            return DebateFraming(
                defence_position="defend the proposition",
                prosecution_position="oppose the proposition",
            )
        if schema is Statement:
            role = "DEF" if "DEFENCE" in system else "PROS"
            return Statement(statement=f"{role} statement via {model}", key_points=["k"])
        if schema is ExaminationTurn:
            role = "DEF" if "DEFENCE" in system else "PROS"
            return ExaminationTurn(
                response=f"{role} via {model}", question_to_opponent="really?",
                rebuttals_to=["pt"],
            )
        if schema is Verdict:
            return Verdict(
                recommendation="I suggest A",
                confidence=0.6,
                grounds=["a"],
                why_alternative_is_weaker=["b"],
                conditions=["holds if X"],
                dissenting_considerations=["y"],
            )
        raise AssertionError(f"unexpected schema {schema}")

    def generate_text(self, model, system, user, **kw):
        self.text_calls.append(model)
        return "examine operational complexity next round"


def test_route_examination_loops_then_closes():
    assert route_examination({"round": 1, "max_rounds": 3}) == "defence_examine"
    assert route_examination({"round": 3, "max_rounds": 3}) == "defence_examine"
    assert route_examination({"round": 4, "max_rounds": 3}) == "defence_closing"
    # 2-round proceeding
    assert route_examination({"round": 3, "max_rounds": 2}) == "defence_closing"


def test_full_three_round_proceeding():
    settings = Settings(verbose=False, max_rounds=3)
    fake = FakeLLM()
    final = run_debate("in-house vs Auth0?", settings, client=fake)

    record = final["record"]
    openings = [e for e in record if e.phase == "opening"]
    exams = [e for e in record if e.phase == "examination"]
    closings = [e for e in record if e.phase == "closing"]
    assert len(openings) == 2  # defence + prosecution
    assert len(exams) == 6  # 3 rounds * 2 counsel
    assert len(closings) == 2
    # both sides examined in every round
    for r in (1, 2, 3):
        assert {e.role for e in exams if e.round == r} == {"defence", "prosecution"}
    # bench speaks after openings and after each of the 3 rounds (the last
    # reflection informs the closing rather than opening a 4th round)
    assert len(final["judge_directions"]) == 4
    assert final["round"] == 4  # advanced past max_rounds to reach closing
    assert isinstance(final["final_verdict"], Verdict)
    # explicit positions framed up front and threaded into state (Decision 2)
    assert final["defence_position"] == "defend the proposition"
    assert final["prosecution_position"] == "oppose the proposition"
    assert (settings.judge_model, "DebateFraming") in fake.json_calls
    assert (settings.judge_model, "Verdict") in fake.json_calls
    assert sum(1 for _, s in fake.json_calls if s == "Statement") == 4  # 2 open + 2 close
    assert sum(1 for _, s in fake.json_calls if s == "ExaminationTurn") == 6


def test_two_round_proceeding_terminates_early():
    settings = Settings(verbose=False, max_rounds=2)
    final = run_debate("monolith vs microservices?", settings, client=FakeLLM())
    assert len([e for e in final["record"] if e.phase == "examination"]) == 4
    assert isinstance(final["final_verdict"], Verdict)


def test_three_labs_used_per_role():
    settings = Settings(verbose=False, max_rounds=2)
    fake = FakeLLM()
    run_debate("q?", settings, client=fake)
    models_used = {m for m, _ in fake.json_calls} | set(fake.text_calls)
    assert settings.defence_model in models_used
    assert settings.prosecution_model in models_used
    assert settings.judge_model in models_used


def test_initial_state_shape():
    s = initial_state("q", Settings(max_rounds=3, history_mode="full"))
    assert s["round"] == 0 and s["max_rounds"] == 3 and s["history_mode"] == "full"
    assert s["record"] == [] and s["final_verdict"] is None
