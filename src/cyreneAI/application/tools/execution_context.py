from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


def _empty_metadata() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class _ToolExecutionContext:
    session_id: str | None = None
    provider_id: str | None = None
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)


_CURRENT_TOOL_EXECUTION_CONTEXT: ContextVar[_ToolExecutionContext | None] = ContextVar(
    "cyreneai_tool_execution_context",
    default=None,
)


@contextmanager
def use_tool_execution_context(
    *,
    session_id: str | None = None,
    provider_id: str | None = None,
    model: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[None]:
    token = _CURRENT_TOOL_EXECUTION_CONTEXT.set(
        _ToolExecutionContext(
            session_id=session_id,
            provider_id=provider_id,
            model=model,
            metadata=(metadata or {}).copy(),
        )
    )
    try:
        yield
    finally:
        _CURRENT_TOOL_EXECUTION_CONTEXT.reset(token)


def get_tool_execution_context() -> _ToolExecutionContext | None:
    return _CURRENT_TOOL_EXECUTION_CONTEXT.get()


__all__ = ["get_tool_execution_context", "use_tool_execution_context"]
