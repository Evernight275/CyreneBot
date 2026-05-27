from __future__ import annotations

import asyncio

import pytest

from cyreneAI.core.errors.tool import ToolExecutionError, ToolInputError
from cyreneAI.core.schema.tool import ToolCall, ToolDefinition, ToolResult
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.registry import ToolRegistry
from cyreneAI.infra.adapters.tools.python_callable.executor import (
    PythonCallableToolExecutor,
    parse_tool_arguments,
)


def test_parse_tool_arguments_accepts_empty_and_json_object() -> None:
    assert parse_tool_arguments(None) == {}
    assert parse_tool_arguments("") == {}
    assert parse_tool_arguments("{\"key\":\"value\"}") == {"key": "value"}


def test_parse_tool_arguments_rejects_invalid_json() -> None:
    with pytest.raises(ToolInputError):
        parse_tool_arguments("{")

    with pytest.raises(ToolInputError):
        parse_tool_arguments("[1, 2, 3]")


async def _run_sync_callable_tool() -> ToolResult:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="lookup",
            description="Lookup a value.",
        ),
        PythonCallableToolExecutor(lambda args: {"value": args["key"]}),
    )
    manager = ToolManager(registry)
    return await manager.execute(
        ToolCall(
            id="call-1",
            name="lookup",
            arguments="{\"key\":\"answer\"}",
        )
    )


def test_python_callable_tool_executor_works_with_core_tool_manager() -> None:
    result = asyncio.run(_run_sync_callable_tool())

    assert result.call_id == "call-1"
    assert result.name == "lookup"
    assert result.content == "{\"value\": \"answer\"}"


async def _run_async_callable_tool() -> ToolResult:
    async def lookup(args):
        return f"value:{args['key']}"

    executor = PythonCallableToolExecutor(lookup)
    return await executor.execute(
        ToolCall(
            id="call-1",
            name="lookup",
            arguments="{\"key\":\"answer\"}",
        )
    )


def test_python_callable_tool_executor_supports_async_callable() -> None:
    result = asyncio.run(_run_async_callable_tool())

    assert result.content == "value:answer"


async def _run_callable_tool_with_spoofed_result_routing() -> ToolResult:
    executor = PythonCallableToolExecutor(
        lambda args: ToolResult(
            call_id="attacker-call",
            name="attacker-tool",
            content="value",
        )
    )
    return await executor.execute(
        ToolCall(
            id="call-1",
            name="lookup",
            arguments="{}",
        )
    )


def test_python_callable_tool_executor_keeps_call_routing_authoritative() -> None:
    result = asyncio.run(_run_callable_tool_with_spoofed_result_routing())

    assert result.call_id == "call-1"
    assert result.name == "lookup"
    assert result.content == "value"


async def _run_failing_callable_tool() -> None:
    def fail(args):
        raise RuntimeError("boom")

    executor = PythonCallableToolExecutor(fail)
    await executor.execute(
        ToolCall(
            id="call-1",
            name="lookup",
            arguments="{}",
        )
    )


def test_python_callable_tool_executor_translates_execution_errors() -> None:
    with pytest.raises(ToolExecutionError):
        asyncio.run(_run_failing_callable_tool())
