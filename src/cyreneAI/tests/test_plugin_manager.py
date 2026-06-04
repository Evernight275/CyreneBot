from __future__ import annotations

import pytest

from cyreneAI.core.errors.plugin import (
    PluginAuthorizationError,
    PluginExecutionError,
)
from cyreneAI.core.plugin.manager import PluginManager
from cyreneAI.core.plugin.registry import PluginRegistry
from cyreneAI.core.schema.bot import BotCommand
from cyreneAI.core.schema.chat import ChatRequest, ChatResponse
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginDefinition,
    PluginEvent,
    PluginEventDefinition,
    PluginEventRequest,
    PluginEventResult,
    PluginEventType,
    PluginLifecycleStatus,
    PluginMiddlewareDefinition,
    PluginMiddlewareRequest,
    PluginMiddlewareType,
    PluginStatusReport,
    PluginTaskDefinition,
)


class _RecordingPluginExecutor:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[PluginCommandRequest] = []
        self.error = error

    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return PluginCommandResult(metadata={"plugin": "help"})


class _RecordingPluginEventExecutor:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[PluginEventRequest] = []
        self.error = error

    async def execute(self, request: PluginEventRequest) -> PluginEventResult:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return PluginEventResult(metadata={"event": request.event.text})


class _RecordingPluginMiddlewareExecutor:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls
        self.requests: list[PluginMiddlewareRequest] = []

    async def execute(
        self,
        request: PluginMiddlewareRequest,
        next_call,
    ) -> ChatResponse:
        self.requests.append(request)
        self.calls.append(f"{self.name}:before")
        updated = request.model_copy(
            update={
                "chat_request": request.chat_request.model_copy(
                    update={
                        "metadata": {
                            **request.chat_request.metadata,
                            self.name: "seen",
                        }
                    }
                )
            }
        )
        response = await next_call(updated)
        self.calls.append(f"{self.name}:after")
        return response


class _FailingPluginMiddlewareExecutor:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def execute(
        self, request: PluginMiddlewareRequest, next_call
    ) -> ChatResponse:
        raise self.error


def _definition(*, admin_required: bool = False) -> PluginDefinition:
    return PluginDefinition(
        plugin_id="builtin.help",
        name="Help",
        description="Show available commands.",
        commands=[
            PluginCommandDefinition(
                name="help",
                description="Show available commands.",
                admin_required=admin_required,
            )
        ],
        events=[
            PluginEventDefinition(
                event_type=PluginEventType.MESSAGE,
                description="Observe messages.",
            )
        ],
        tasks=[
            PluginTaskDefinition(
                name="cleanup",
                description="Clean up plugin state.",
            )
        ],
        middlewares=[
            PluginMiddlewareDefinition(
                middleware_type=PluginMiddlewareType.LLM,
                description="Trace LLM calls.",
            )
        ],
    )


def _request(*, is_admin: bool = False) -> PluginCommandRequest:
    return PluginCommandRequest(
        command=BotCommand(raw_text="/help", name="help"),
        is_admin=is_admin,
    )


def test_plugin_manager_lists_plugins_and_commands() -> None:
    definition = _definition()
    registry = PluginRegistry()
    registry.register(definition, _RecordingPluginExecutor())
    manager = PluginManager(registry)

    assert manager.list_plugins() == [definition]
    assert manager.list_commands() == definition.commands
    assert manager.list_events() == definition.events
    assert manager.list_tasks() == definition.tasks
    assert manager.list_middlewares() == definition.middlewares
    assert manager.get_plugin(definition.plugin_id) == definition
    assert manager.list_plugin_commands(definition.plugin_id) == definition.commands
    assert manager.list_plugin_events(definition.plugin_id) == definition.events
    assert manager.list_plugin_tasks(definition.plugin_id) == definition.tasks
    assert (
        manager.list_plugin_middlewares(definition.plugin_id) == definition.middlewares
    )
    assert (
        manager.get_plugin_status(definition.plugin_id).plugin_id
        == definition.plugin_id
    )


def test_plugin_manager_gets_failed_status_without_definition() -> None:
    registry = PluginRegistry()
    registry.record_status(
        PluginStatusReport(
            plugin_id="thirdparty.failed",
            status=PluginLifecycleStatus.FAILED,
            reason="register_conflict",
            commands=[
                PluginCommandDefinition(
                    name="hello",
                    description="Say hello.",
                )
            ],
        )
    )
    manager = PluginManager(registry)

    status = manager.get_plugin_status("thirdparty.failed")

    assert status.plugin_id == "thirdparty.failed"
    assert status.reason == "register_conflict"
    assert status.commands[0].name == "hello"


async def _run_execute_command() -> None:
    executor = _RecordingPluginExecutor()
    registry = PluginRegistry()
    registry.register(_definition(), executor)
    manager = PluginManager(registry)
    request = _request()

    result = await manager.execute_command(request)

    assert executor.calls == [request]
    assert result.metadata == {"plugin": "help"}


def test_plugin_manager_executes_command() -> None:
    import asyncio

    asyncio.run(_run_execute_command())


async def _run_admin_required_rejects_non_admin() -> None:
    registry = PluginRegistry()
    registry.register(_definition(admin_required=True), _RecordingPluginExecutor())
    manager = PluginManager(registry)

    with pytest.raises(PluginAuthorizationError):
        await manager.execute_command(_request(is_admin=False))


def test_plugin_manager_rejects_admin_command_for_non_admin() -> None:
    import asyncio

    asyncio.run(_run_admin_required_rejects_non_admin())


async def _run_admin_required_allows_admin() -> None:
    executor = _RecordingPluginExecutor()
    registry = PluginRegistry()
    registry.register(_definition(admin_required=True), executor)
    manager = PluginManager(registry)

    result = await manager.execute_command(_request(is_admin=True))

    assert result.metadata == {"plugin": "help"}


def test_plugin_manager_allows_admin_command_for_admin() -> None:
    import asyncio

    asyncio.run(_run_admin_required_allows_admin())


async def _run_wraps_unexpected_errors() -> None:
    error = RuntimeError("boom")
    registry = PluginRegistry()
    registry.register(_definition(), _RecordingPluginExecutor(error=error))
    manager = PluginManager(registry)

    with pytest.raises(PluginExecutionError) as caught:
        await manager.execute_command(_request())

    assert caught.value.cause is error


def test_plugin_manager_wraps_unexpected_errors() -> None:
    import asyncio

    asyncio.run(_run_wraps_unexpected_errors())


async def _run_dispatch_event() -> None:
    executor = _RecordingPluginEventExecutor()
    registry = PluginRegistry()
    registry.register(
        _definition(),
        _RecordingPluginExecutor(),
        event_executor=executor,
    )
    manager = PluginManager(registry)
    event = PluginEvent(
        event_id="event-1",
        event_type=PluginEventType.MESSAGE,
        session_id="session-1",
        text="hello",
    )

    results = await manager.dispatch_event(event, metadata={"source": "test"})

    assert len(executor.calls) == 1
    assert executor.calls[0].event is event
    assert executor.calls[0].metadata == {"source": "test"}
    assert results[0].metadata == {"event": "hello"}


def test_plugin_manager_dispatches_event() -> None:
    import asyncio

    asyncio.run(_run_dispatch_event())


async def _run_execute_llm_middlewares_in_registration_order() -> None:
    calls: list[str] = []
    first = _definition().model_copy(
        update={
            "plugin_id": "plugin.first",
            "name": "First",
            "commands": [
                PluginCommandDefinition(name="first", description="First command."),
            ],
        }
    )
    second = _definition().model_copy(
        update={
            "plugin_id": "plugin.second",
            "name": "Second",
            "commands": [
                PluginCommandDefinition(name="second", description="Second command."),
            ],
        }
    )
    first_executor = _RecordingPluginMiddlewareExecutor("first", calls)
    second_executor = _RecordingPluginMiddlewareExecutor("second", calls)
    registry = PluginRegistry()
    registry.register(
        first,
        _RecordingPluginExecutor(),
        middleware_executor=first_executor,
    )
    registry.register(
        second,
        _RecordingPluginExecutor(),
        middleware_executor=second_executor,
    )
    manager = PluginManager(registry)

    async def final(chat_request: ChatRequest) -> ChatResponse:
        calls.append("provider")
        return ChatResponse(
            provider_id=chat_request.provider_id,
            model=chat_request.model,
            raw={"metadata": dict(chat_request.metadata)},
        )

    response = await manager.execute_llm_middlewares(
        ChatRequest(
            provider_id="provider-1",
            model="model",
            messages=[],
        ),
        final,
    )

    assert calls == [
        "first:before",
        "second:before",
        "provider",
        "second:after",
        "first:after",
    ]
    assert response.raw == {
        "metadata": {
            "first": "seen",
            "second": "seen",
        }
    }
    assert first_executor.requests[0].metadata == {"plugin_id": "plugin.first"}
    assert second_executor.requests[0].metadata == {"plugin_id": "plugin.second"}


def test_plugin_manager_executes_llm_middlewares_in_registration_order() -> None:
    import asyncio

    asyncio.run(_run_execute_llm_middlewares_in_registration_order())


async def _run_execute_llm_middlewares_wraps_unexpected_errors() -> None:
    error = RuntimeError("boom")
    definition = _definition()
    registry = PluginRegistry()
    registry.register(
        definition,
        _RecordingPluginExecutor(),
        middleware_executor=_FailingPluginMiddlewareExecutor(error),
    )
    manager = PluginManager(registry)

    async def final(chat_request: ChatRequest) -> ChatResponse:
        return ChatResponse(provider_id=chat_request.provider_id)

    with pytest.raises(PluginExecutionError) as caught:
        await manager.execute_llm_middlewares(
            ChatRequest(
                provider_id="provider-1",
                model="model",
                messages=[],
            ),
            final,
        )

    assert caught.value.cause is error


def test_plugin_manager_wraps_unexpected_middleware_errors() -> None:
    import asyncio

    asyncio.run(_run_execute_llm_middlewares_wraps_unexpected_errors())
