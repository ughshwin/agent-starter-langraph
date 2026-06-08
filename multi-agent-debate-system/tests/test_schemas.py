import pytest
from pydantic import ValidationError

from debate.schemas import CourtRecordEntry, ExaminationTurn, Statement, Verdict


def test_statement_defaults_key_points_empty():
    s = Statement(statement="building in-house gives control")
    assert s.key_points == []


def test_examination_turn_defaults_rebuttals_empty():
    t = ExaminationTurn(response="we hold our position", question_to_opponent="and the cost?")
    assert t.rebuttals_to == []


def test_court_record_entry_carries_phase_and_round():
    e = CourtRecordEntry(phase="examination", round=2, role="defence", text="x",
                         question="why?", rebuttals_to=["cost claim"])
    assert e.phase == "examination" and e.round == 2 and e.role == "defence"
    assert e.question == "why?" and e.rebuttals_to == ["cost claim"]


def test_verdict_confidence_must_be_in_unit_interval():
    base = dict(
        recommendation="I suggest using Auth0",
        grounds=["time-to-value"],
        why_alternative_is_weaker=["maintenance burden"],
        conditions=["holds if team < 10"],
        dissenting_considerations=["lock-in"],
    )
    Verdict(confidence=0.0, **base)
    Verdict(confidence=1.0, **base)
    with pytest.raises(ValidationError):
        Verdict(confidence=1.5, **base)
    with pytest.raises(ValidationError):
        Verdict(confidence=-0.1, **base)


def test_verdict_requires_all_structured_fields():
    with pytest.raises(ValidationError):
        Verdict(recommendation="x", confidence=0.5)  # missing list fields
