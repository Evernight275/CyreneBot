from __future__ import annotations

import json
from typing import Any

import pytest

from cyreneAI.api._executors import (
    _CommandHandlerExecutor,
    _EventHandlerExecutor,
    _MiddlewareHandlerExecutor,
    _TaskHandlerExecutor,
    _ToolHandlerExecutor,
)
from cyreneAI.core.errors.plugin import PluginExecutionError
from cyreneAI.core.errors.tool import ToolExecutionError, ToolInputError
from cyreneAI.core.schema.bot import BotCommand
from cyreneAI.core.schema.chat import ChatRequest
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginEvent,
    PluginEventDefinition,
    PluginEventRequest,
    PluginEventResult,
    PluginEventType,
    PluginMiddlewareDefinition,
    PluginMiddlewareRequest,
    PluginMiddlewareType,
    PluginTaskDefinition,
    PluginTaskRequest,
    PluginTaskResult,
)
from cyreneAI.core.schema.tool import ToolCall, ToolResult


def _command_request() -> PluginCommandRequest:
    return PluginCommandRequest(
        command=BotCommand(raw_text="/boom", name="boom"),
    )


def _task_request() -> PluginTaskRequest:
    return PluginTaskRequest(
        task=PluginTaskDefinition(name="sync"),
    )


def _event_request() -> PluginEventRequest:
    return PluginEventRequest(
        route=PluginEventDefinition(event_type=PluginEventType.MESSAGE),
        event=PluginEvent(
            event_id="event-1",
            event_type=PluginEventType.MESSAGE,
            session_id="session-1",
        ),
    )


def _middleware_request() -> PluginMiddlewareRequest:
    return PluginMiddlewareRequest(
        route=PluginMiddlewareDefinition(middleware_type=PluginMiddlewareType.LLM),
        chat_request=ChatRequest(provider_id="provider-1", model="model-1", messages=[]),
    )


def _tool_call(arguments: dict[str, Any] | str | None = None) -> ToolCall:
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments)
    return ToolCall(id="call-1", name="lookup", arguments=arguments)


@pytest.mark.asyncio
async def test_command_executor_wraps_unexpected_handler_errors() -> None:
    cause = RuntimeError("handler failed")

    def handler() -> None:
        raise cause

    executor = _CommandHandlerExecutor(
        handler,
        runtime_context=object(),
        definition=PluginCommandDefinition(name="boom", description="Boom."),
    )

    with pytest.raises(PluginExecutionError) as exc_info:
        await executor.execute(_command_request())

    assert str(exc_info.value) == "插件命令 boom 执行失败"
    assert exc_info.value.cause is cause


@pytest.mark.asyncio
async def test_task_executor_wraps_errors_and_rejects_bad_results() -> None:
    cause = RuntimeError("task failed")

    def failing_handler() -> None:
        raise cause

    failing_executor = _TaskHandlerExecutor(failing_handler, runtime_context=object())
    with pytest.raises(PluginExecutionError) as exc_info:
        await failing_executor.execute(_task_request())

    assert str(exc_info.value) == "插件任务 sync 执行失败"
    assert exc_info.value.cause is cause

    bad_executor = _TaskHandlerExecutor(lambda: "bad", runtime_context=object())
    with pytest.raises(PluginExecutionError) as bad_exc_info:
        await bad_executor.execute(_task_request())

    assert str(bad_exc_info.value) == "插件任务 sync 必须返回 PluginTaskResult 或 None"

    none_executor = _TaskHandlerExecutor(lambda: None, runtime_context=object())
    assert await none_executor.execute(_task_request()) == PluginTaskResult()


@pytest.mark.asyncio
async def test_event_executor_wraps_errors_and_rejects_bad_results() -> None:
    cause = RuntimeError("event failed")

    async def failing_handler() -> None:
        raise cause

    failing_executor = _EventHandlerExecutor(failing_handler, runtime_context=object())
    with pytest.raises(PluginExecutionError) as exc_info:
        await failing_executor.execute(_event_request())

    assert str(exc_info.value) == "插件事件 message 执行失败"
    assert exc_info.value.cause is cause

    bad_executor = _EventHandlerExecutor(lambda: object(), runtime_context=object())
    with pytest.raises(PluginExecutionError) as bad_exc_info:
        await bad_executor.execute(_event_request())

    assert str(bad_exc_info.value) == "插件事件 message 必须返回 PluginEventResult 或 None"

    none_executor = _EventHandlerExecutor(lambda: None, runtime_context=object())
    assert await none_executor.execute(_event_request()) == PluginEventResult()


@pytest.mark.asyncio
async def test_middleware_executor_injects_next_call_and_wraps_errors() -> None:
    async def handler(call_next):
        return await call_next("payload")

    async def next_call(value: str) -> str:
        return f"next:{value}"

    executor = _MiddlewareHandlerExecutor(handler, runtime_context=object())

    assert await executor.execute(_middleware_request(), next_call) == "next:payload"

    cause = RuntimeError("middleware failed")

    def failing_handler() -> None:
        raise cause

    failing_executor = _MiddlewareHandlerExecutor(
        failing_handler,
        runtime_context=object(),
    )
    with pytest.raises(PluginExecutionError) as exc_info:
        await failing_executor.execute(_middleware_request(), next_call)

    assert str(exc_info.value) == "插件中间件 llm 执行失败"
    assert exc_info.value.cause is cause


@pytest.mark.asyncio
async def test_tool_executor_binds_arguments_context_and_call() -> None:
    runtime_context = {"name": "runtime"}

    async def handler(
        call: ToolCall,
        context,
        *,
        query: str,
        limit: int = 3,
    ) -> dict[str, Any]:
        return {
            "call_id": call.id,
            "limit": limit,
            "query": query,
            "runtime": context["name"],
        }

    executor = _ToolHandlerExecutor(handler, runtime_context=runtime_context)

    result = await executor.execute(_tool_call({"query": "cyrene"}))

    assert result == ToolResult(
        call_id="call-1",
        name="lookup",
        content='{"call_id": "call-1", "limit": 3, "query": "cyrene", '
        '"runtime": "runtime"}',
    )


@pytest.mark.asyncio
async def test_tool_executor_wraps_unexpected_handler_errors() -> None:
    cause = RuntimeError("tool failed")

    def handler() -> None:
        raise cause

    executor = _ToolHandlerExecutor(handler, runtime_context=object())

    with pytest.raises(ToolExecutionError) as exc_info:
        await executor.execute(_tool_call({}))

    assert str(exc_info.value) == "插件工具 lookup 执行失败"
    assert exc_info.value.cause is cause


@pytest.mark.asyncio
async def test_tool_executor_rejects_invalid_arguments() -> None:
    executor = _ToolHandlerExecutor(lambda value: value, runtime_context=object())

    with pytest.raises(ToolInputError, match="valid JSON"):
        await executor.execute(_tool_call("{"))

    with pytest.raises(ToolInputError, match="JSON object"):
        await executor.execute(_tool_call("[]"))

    with pytest.raises(ToolInputError, match="value is required"):
        await executor.execute(_tool_call({}))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "arguments", "message"),
    [
        (lambda value: value, {"value": 1}, "value must be a string"),
        (lambda value: value, {"value": True}, "value must be an integer"),
        (lambda value: value, {"value": True}, "value must be a number"),
        (lambda value: value, {"value": "true"}, "value must be a boolean"),
    ],
)
async def test_tool_executor_rejects_bad_typed_arguments(
    handler,
    arguments: dict[str, Any],
    message: str,
) -> None:
    if "string" in message:
        def typed_handler(value: str) -> str:
            return value
    elif "integer" in message:
        def typed_handler(value: int) -> int:
            return value
    elif "number" in message:
        def typed_handler(value: float) -> float:
            return value
    else:
        def typed_handler(value: bool) -> bool:
            return value

    executor = _ToolHandlerExecutor(typed_handler, runtime_context=object())

    with pytest.raises(ToolInputError, match=message):
        await executor.execute(_tool_call(arguments))


@pytest.mark.asyncio
async def test_tool_executor_rejects_unsupported_parameter_kinds() -> None:
    def handler(*values) -> None:
        return None

    executor = _ToolHandlerExecutor(handler, runtime_context=object())

    with pytest.raises(ToolInputError, match="Unsupported tool handler parameter"):
        await executor.execute(_tool_call({"values": ["bad"]}))


@pytest.mark.asyncio
async def test_tool_executor_coerces_supported_result_shapes() -> None:
    tool_result_executor = _ToolHandlerExecutor(
        lambda: ToolResult(call_id="old", name="old", content="ok"),
        runtime_context=object(),
    )
    none_executor = _ToolHandlerExecutor(lambda: None, runtime_context=object())
    text_executor = _ToolHandlerExecutor(lambda: 42, runtime_context=object())

    assert await tool_result_executor.execute(_tool_call({})) == ToolResult(
        call_id="call-1",
        name="lookup",
        content="ok",
    )
    assert await none_executor.execute(_tool_call({})) == ToolResult(
        call_id="call-1",
        name="lookup",
        content="",
    )
    assert await text_executor.execute(_tool_call({})) == ToolResult(
        call_id="call-1",
        name="lookup",
        content="42",
    )
