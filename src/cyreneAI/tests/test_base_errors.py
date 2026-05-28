from __future__ import annotations

from cyreneAI.core.errors.base import ConfigurationError, CyreneAIError


def test_base_error_info_uses_error_class_name() -> None:
    error = CyreneAIError("failed")

    assert error.error_info == "CyreneAIError"


def test_child_error_info_uses_child_class_name() -> None:
    error = ConfigurationError("bad config")

    assert error.error_info == "ConfigurationError"


def test_base_error_keeps_message_and_cause() -> None:
    cause = RuntimeError("boom")
    error = CyreneAIError("failed", cause=cause)

    assert str(error) == "failed"
    assert error.cause is cause
