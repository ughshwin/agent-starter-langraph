"""LLM access layer: structured output, thinking mode, timeouts, retries.

The whole point of this module is to make a small local model reliably return a
*valid instance of a Pydantic schema*. We do it at the decode layer with Ollama's
`format=<json-schema>` (grammar-constrained generation) and validate with
Pydantic. If a model still slips (e.g. an older server ignoring `format`), we fall
back to lenient JSON extraction, then re-ask with the error fed back.

Agents depend on the `LLMClient` Protocol, not on Ollama directly, so tests can
inject a `FakeLLM` and exercise the whole graph with no model running.
"""

from __future__ import annotations

import json
import re
from typing import Protocol, Type, TypeVar

import ollama
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class DebateLLMError(RuntimeError):
    """Raised when a model call cannot produce a usable result after retries."""


# --- lenient JSON recovery (fallback when format= is ignored) ----------------

def _iter_top_level_json(text: str):
    """Yield each brace-balanced top-level {...} substring in text."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                yield text[start : i + 1]


def _loads_lenient(fragment: str):
    """json.loads tolerating the invalid backslash escapes small models emit."""
    try:
        return json.loads(fragment)
    except json.JSONDecodeError:
        fixed = re.sub(r'\\([^"\\/bfnrtu])', r"\1", fragment)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None


def extract_model(content: str, schema: Type[T]) -> T | None:
    """Best-effort: validate `content` as `schema`, trying whole string then any
    embedded JSON object. Returns None if nothing validates."""
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


# --- client protocol ---------------------------------------------------------

class LLMClient(Protocol):
    def generate_json(
        self,
        model: str,
        system: str,
        user: str,
        schema: Type[T],
        *,
        think: bool = False,
        num_predict: int = 900,
        timeout: float = 240.0,
    ) -> T: ...

    def generate_text(
        self,
        model: str,
        system: str,
        user: str,
        *,
        think: bool = False,
        num_predict: int = 1200,
        timeout: float = 240.0,
    ) -> str: ...


# --- real Ollama implementation ----------------------------------------------

class OllamaLLM:
    """Concrete `LLMClient` over a local Ollama server."""

    def __init__(self, validation_retries: int = 2, log=None):
        self._retries = validation_retries
        self._log = log or (lambda *a, **k: None)

    def _chat(self, model, messages, *, fmt, think, num_predict, timeout):
        """One raw call. `think` is only sent when True so non-thinking models
        (which error on the param) are unaffected. Returns (content, thinking)."""
        client = ollama.Client(timeout=timeout)
        kwargs = dict(model=model, messages=messages, options={"num_predict": num_predict})
        if fmt is not None:
            kwargs["format"] = fmt
        if think:
            kwargs["think"] = True
        try:
            resp = client.chat(**kwargs)
        except Exception as exc:
            # Some models reject think=True ("does not support thinking"); retry once
            # without it rather than failing the whole debate.
            if think and "think" in str(exc).lower():
                kwargs.pop("think", None)
                resp = client.chat(**kwargs)
            else:
                raise DebateLLMError(f"{model} call failed: {type(exc).__name__}: {exc}")
        msg = resp["message"]
        return (msg.get("content") or "", msg.get("thinking") or "")

    def generate_json(self, model, system, user, schema, *, think=False,
                      num_predict=900, timeout=240.0):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        fmt = schema.model_json_schema()
        last_err = "no response"
        for attempt in range(self._retries + 1):
            content, thinking = self._chat(
                model, messages, fmt=fmt, think=think,
                num_predict=num_predict, timeout=timeout,
            )
            if thinking:
                self._log("THINK", thinking.strip())
            parsed = extract_model(content, schema)
            if parsed is not None:
                return parsed
            # Re-ask with the failure made explicit. (Rarely needed when format=
            # is honoured, but this is the survival path.)
            last_err = f"output did not match {schema.__name__}: {content[:200]!r}"
            self._log("RETRY", f"{model} attempt {attempt + 1}: {last_err}")
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": (
                    f"That did not match the required JSON schema for "
                    f"{schema.__name__}. Reply with ONLY a valid JSON object that "
                    f"matches the schema. No prose, no markdown."
                ),
            })
        raise DebateLLMError(f"{model}: {last_err}")

    def generate_text(self, model, system, user, *, think=False,
                      num_predict=1200, timeout=240.0):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        content, thinking = self._chat(
            model, messages, fmt=None, think=think,
            num_predict=num_predict, timeout=timeout,
        )
        if thinking:
            self._log("THINK", thinking.strip())
        text = content.strip()
        if not text:
            raise DebateLLMError(f"{model}: empty text response")
        return text
