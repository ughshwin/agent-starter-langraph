import pytest
from pydantic import ValidationError

from debate.schemas import ArgumentPayload, RoundArgument, Verdict


def test_argument_payload_defaults_rebuttals_empty():
    a = ArgumentPayload(argument="build in-house gives control")
    assert a.rebuttals_to == []


def test_round_argument_carries_round():
    a = RoundArgument(round=2, argument="x", rebuttals_to=["cost claim"])
    assert a.round == 2 and a.rebuttals_to == ["cost claim"]


def test_verdict_confidence_must_be_in_unit_interval():
    base = dict(
        recommendation="use Auth0",
        key_factors=["time-to-value"],
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
