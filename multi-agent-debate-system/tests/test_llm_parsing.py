"""The lenient-recovery fallback: extract_model must validate a schema from clean
JSON, JSON embedded in prose, and JSON with the invalid backslash escapes small
models emit — and return None when nothing matches."""

from debate.llm import extract_model, _loads_lenient
from debate.schemas import ExaminationTurn, Verdict


def test_extract_clean_json():
    out = extract_model(
        '{"response": "x", "question_to_opponent": "why?", "rebuttals_to": ["a"]}',
        ExaminationTurn,
    )
    assert out is not None and out.response == "x" and out.rebuttals_to == ["a"]


def test_extract_json_embedded_in_prose():
    content = (
        'Sure, here it is:\n'
        '{"response": "y", "question_to_opponent": "and cost?", "rebuttals_to": []}\n'
        'hope that helps'
    )
    out = extract_model(content, ExaminationTurn)
    assert out is not None and out.response == "y"


def test_loads_lenient_strips_bad_escapes():
    # invalid JSON: \* is not a legal escape
    obj = _loads_lenient(r'{"response": "6371 \* 2", "question_to_opponent": "?"}')
    assert obj is not None and obj["response"] == "6371 * 2"


def test_extract_returns_none_on_garbage():
    assert extract_model("no json here at all", ExaminationTurn) is None


def test_extract_verdict_full():
    content = (
        '{"recommendation": "I suggest Auth0", "confidence": 0.7, '
        '"grounds": ["speed"], "why_alternative_is_weaker": ["maintenance"], '
        '"conditions": ["holds if small team"], '
        '"dissenting_considerations": ["lock-in"]}'
    )
    out = extract_model(content, Verdict)
    assert out is not None and out.confidence == 0.7
