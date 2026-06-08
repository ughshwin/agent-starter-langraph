"""The lenient-recovery fallback: extract_model must validate a schema from clean
JSON, JSON embedded in prose, and JSON with the invalid backslash escapes small
models emit — and return None when nothing matches."""

from debate.llm import extract_model, _loads_lenient
from debate.schemas import ArgumentPayload, Verdict


def test_extract_clean_json():
    out = extract_model('{"argument": "x", "rebuttals_to": ["a"]}', ArgumentPayload)
    assert out is not None and out.argument == "x" and out.rebuttals_to == ["a"]


def test_extract_json_embedded_in_prose():
    content = 'Sure, here it is:\n{"argument": "y", "rebuttals_to": []}\nhope that helps'
    out = extract_model(content, ArgumentPayload)
    assert out is not None and out.argument == "y"


def test_loads_lenient_strips_bad_escapes():
    # invalid JSON: \* is not a legal escape
    obj = _loads_lenient(r'{"argument": "6371 \* 2", "rebuttals_to": []}')
    assert obj is not None and obj["argument"] == "6371 * 2"


def test_extract_returns_none_on_garbage():
    assert extract_model("no json here at all", ArgumentPayload) is None


def test_extract_verdict_full():
    content = (
        '{"recommendation": "use Auth0", "confidence": 0.7, '
        '"key_factors": ["speed"], "conditions": ["holds if small team"], '
        '"dissenting_considerations": ["lock-in"]}'
    )
    out = extract_model(content, Verdict)
    assert out is not None and out.confidence == 0.7
