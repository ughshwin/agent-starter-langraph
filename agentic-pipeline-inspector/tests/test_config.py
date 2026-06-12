import pytest
from inspector.config import Settings


def test_defaults():
    s = Settings()
    assert s.model == "qwen2.5:3b"
    assert s.tool_timeout > 0
    s.validate()


def test_validate_rejects_bad_timeout():
    with pytest.raises(ValueError):
        Settings(tool_timeout=0).validate()
