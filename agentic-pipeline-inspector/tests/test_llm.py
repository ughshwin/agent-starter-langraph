from pydantic import BaseModel

from inspector.llm import extract_model


class Foo(BaseModel):
    a: int
    b: str


def test_extract_model_clean_json():
    assert extract_model('{"a": 1, "b": "x"}', Foo) == Foo(a=1, b="x")


def test_extract_model_embedded_json():
    txt = 'Here you go:\n{"a": 2, "b": "y"}\nthanks'
    assert extract_model(txt, Foo) == Foo(a=2, b="y")


def test_extract_model_returns_none_on_failure():
    assert extract_model("no json here", Foo) is None
