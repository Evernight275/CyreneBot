from __future__ import annotations

import pytest

from cyreneAI.core.errors.plugin import (
    PluginAuthorizationError,
    PluginExecutionError,
)
from cyreneAI.core.plugin.manager import PluginManager
from cyreneAI.core.plugin.registry import PluginRegistry
from cyreneAI.core.schema.bot import BotCommand
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
    assert manager.get_plugin(definition.plugin_id) == definition
    assert manager.list_plugin_commands(definition.plugin_id) == definition.commands
    assert manager.list_plugin_events(definition.plugin_id) == definition.events
    assert manager.list_plugin_tasks(definition.plugin_id) == definition.tasks
    assert manager.get_plugin_status(definition.plugin_id).plugin_id == definition.plugin_id


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
