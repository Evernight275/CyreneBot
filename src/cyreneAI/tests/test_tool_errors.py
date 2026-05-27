from __future__ import annotations

from cyreneAI.core.errors.base import (
    ConfigurationError,
    NotFoundError,
    RequestError,
    ResponseError,
    StateError,
    ValidationError,
)
from cyreneAI.core.errors.tool import (
    ToolConfigurationError,
    ToolError,
    ToolExecutionError,
    ToolInputError,
    ToolNotFoundError,
    ToolResultError,
    ToolStateError,
)


def test_tool_errors_belong_to_tool_family() -> None:
    errors = [
        ToolInputError("bad input"),
        ToolNotFoundError("missing tool"),
        ToolConfigurationError("bad config"),
        ToolExecutionError("execution failed"),
        ToolResultError("bad result"),
        ToolStateError("bad state"),
    ]

    assert all(isinstance(error, ToolError) for error in errors)


def test_tool_errors_map_to_base_error_categories() -> None:
    assert isinstance(ToolInputError("bad input"), ValidationError)
    assert isinstance(ToolNotFoundError("missing tool"), NotFoundError)
    assert isinstance(ToolConfigurationError("bad config"), ConfigurationError)
    assert isinstance(ToolExecutionError("execution failed"), RequestError)
    assert isinstance(ToolResultError("bad result"), ResponseError)
    assert isinstance(ToolStateError("bad state"), StateError)


def test_tool_error_keeps_cause() -> None:
    cause = RuntimeError("boom")
    error = ToolExecutionError("execution failed", cause=cause)

    assert error.cause is cause
