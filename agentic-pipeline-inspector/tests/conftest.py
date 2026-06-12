import pytest

from inspector.schemas import DepthPlan, ExecutiveSummary


class FakeLLM:
    """Returns valid instances of whatever schema is asked for. No model needed."""

    def __init__(self, depths="standard", summary="Audit complete."):
        self._depths = depths
        self._summary = summary

    def generate_json(self, system, user, schema):
        if schema is DepthPlan:
            return DepthPlan(security=self._depths, code_quality=self._depths,
                             container=self._depths, dependencies=self._depths,
                             operational=self._depths)
        if schema is ExecutiveSummary:
            return ExecutiveSummary(summary=self._summary)
        raise AssertionError(f"unexpected schema {schema}")


@pytest.fixture
def fake_llm():
    return FakeLLM()
