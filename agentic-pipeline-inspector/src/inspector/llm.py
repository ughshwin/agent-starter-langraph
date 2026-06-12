"""LLM access: grammar-constrained structured output over a local Ollama model.

Agents depend on the `LLMClient` Protocol, so tests inject a `FakeLLM` and the
whole graph runs with no model. Adapted from the debate system's llm.py.
"""
from __future__ import annotations

import json
import re
from typing import Protocol, Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class InspectorLLMError(RuntimeError):
    """Raised when a model call cannot produce a usable result after retries."""


def _iter_top_level_json(text: str):
    depth, start = 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                yield text[start:i + 1]


def _loads_lenient(fragment: str):
    try:
        return json.loads(fragment)
    except json.JSONDecodeError:
        fixed = re.sub(r'\\([^"\\/bfnrtu])', r"\1", fragment)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None


def extract_model(content: str, schema: Type[T]) -> T | None:
    try:
        return schema.model_validate_json(content)
    except ValidationError:
        pass
    for fragment in _iter_top_level_json(content):
        obj = _loads_lenient(fragment)
        if isinstance(obj, dict):
            try:
                return schema.model_validate(obj)
            except ValidationError:
                continue
    return None


class LLMClient(Protocol):
    def generate_json(self, system: str, user: str, schema: Type[T]) -> T: ...


class OllamaLLM:
    """Concrete `LLMClient` over a local Ollama server."""

    def __init__(self, model: str, *, timeout: float = 240.0, num_predict: int = 700,
                 retries: int = 2, log=None):
        self._model = model
        self._timeout = timeout
        self._num_predict = num_predict
        self._retries = retries
        self._log = log or (lambda *a, **k: None)

    def generate_json(self, system: str, user: str, schema: Type[T]) -> T:
        import ollama
        client = ollama.Client(timeout=self._timeout)
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        fmt = schema.model_json_schema()
        last_err = "no response"
        for attempt in range(self._retries + 1):
            try:
                resp = client.chat(model=self._model, messages=messages, format=fmt,
                                   options={"num_predict": self._num_predict})
            except Exception as exc:
                raise InspectorLLMError(
                    f"{self._model} call failed: {type(exc).__name__}: {exc}")
            content = resp["message"].get("content") or ""
            parsed = extract_model(content, schema)
            if parsed is not None:
                return parsed
            last_err = f"did not match {schema.__name__}: {content[:200]!r}"
            self._log("RETRY", f"attempt {attempt + 1}: {last_err}")
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content":
                f"That did not match the required JSON schema for {schema.__name__}. "
                f"Reply with ONLY a valid JSON object matching the schema."})
        raise InspectorLLMError(f"{self._model}: {last_err}")
