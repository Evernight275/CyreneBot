from __future__ import annotations

from cyreneAI.core.errors.base import (
    DependencyError,
    NotFoundError,
    RequestError,
    ResponseError,
    StateError,
    UnsupportedError,
    ValidationError,
)
from cyreneAI.core.errors.context import (
    ContextBudgetError,
    ContextCompressionError,
    ContextError,
    ContextInputError,
    ContextNotFoundError,
    ContextRetrievalError,
    ContextStateError,
    ContextStoreError,
    ContextUnsupportedError,
    ContextWindowError,
)


def test_context_errors_belong_to_context_family() -> None:
    errors = [
        ContextInputError("bad input"),
        ContextNotFoundError("missing context"),
        ContextStateError("bad state"),
        ContextBudgetError("budget exceeded"),
        ContextWindowError("window failed"),
        ContextCompressionError("compression failed"),
        ContextRetrievalError("retrieval failed"),
        ContextStoreError("store failed"),
        ContextUnsupportedError("unsupported"),
    ]

    assert all(isinstance(error, ContextError) for error in errors)


def test_context_errors_map_to_base_error_categories() -> None:
    assert isinstance(ContextInputError("bad input"), ValidationError)
    assert isinstance(ContextNotFoundError("missing context"), NotFoundError)
    assert isinstance(ContextStateError("bad state"), StateError)
    assert isinstance(ContextBudgetError("budget exceeded"), RequestError)
    assert isinstance(ContextWindowError("window failed"), RequestError)
    assert isinstance(ContextCompressionError("compression failed"), ResponseError)
    assert isinstance(ContextRetrievalError("retrieval failed"), ResponseError)
    assert isinstance(ContextStoreError("store failed"), DependencyError)
    assert isinstance(ContextUnsupportedError("unsupported"), UnsupportedError)


def test_context_error_keeps_cause() -> None:
    cause = RuntimeError("boom")
    error = ContextStoreError("store failed", cause=cause)

    assert error.cause is cause
