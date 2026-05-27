from __future__ import annotations

import pytest

from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.tool import ToolNotFoundError
from cyreneAI.core.schema.tool import ToolCall, ToolDefinition, ToolResult
from cyreneAI.core.tool.registry import ToolRegistry


class FakeToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=call.arguments,
        )


def _definition(name: str = "lookup") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="Lookup a value.",
        parameters_schema={
            "type": "object",
            "properties": {},
        },
    )


def test_tool_registry_registers_and_lists_tools() -> None:
    registry = ToolRegistry()
    executor = FakeToolExecutor()
    definition = _definition()

    registry.register(definition, executor)

    assert registry.exists("lookup")
    assert registry.get_definition("lookup") is definition
    assert registry.get_executor("lookup") is executor
    assert registry.list_definitions() == [definition]


def test_tool_registry_rejects_duplicate_tools() -> None:
    registry = ToolRegistry()

    registry.register(_definition(), FakeToolExecutor())

    with pytest.raises(ConflictError):
        registry.register(_definition(), FakeToolExecutor())


def test_tool_registry_raises_when_tool_is_missing() -> None:
    registry = ToolRegistry()

    with pytest.raises(ToolNotFoundError):
        registry.get_definition("missing")

    with pytest.raises(ToolNotFoundError):
        registry.get_executor("missing")

    with pytest.raises(ToolNotFoundError):
        registry.unregister("missing")


def test_tool_registry_unregisters_tools() -> None:
    registry = ToolRegistry()

    registry.register(_definition(), FakeToolExecutor())
    registry.unregister("lookup")

    assert not registry.exists("lookup")
