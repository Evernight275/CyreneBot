from __future__ import annotations

import pytest

from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.plugin import PluginNotFoundError, PluginStateError
from cyreneAI.core.plugin.registry import PluginRegistry
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
    PluginStatusReport,
    PluginTaskDefinition,
)


class _FakePluginExecutor:
    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        return PluginCommandResult(metadata={"command": request.command.name})


class _FakePluginEventExecutor:
    async def execute(self, request: PluginEventRequest) -> PluginEventResult:
        return PluginEventResult(metadata={"event": request.event.event_type})


def _definition(
    plugin_id: str = "builtin.help",
    *,
    command_name: str = "help",
    aliases: list[str] | None = None,
    enabled: bool = True,
    command_enabled: bool = True,
    events: list[PluginEventDefinition] | None = None,
    tasks: list[PluginTaskDefinition] | None = None,
) -> PluginDefinition:
    return PluginDefinition(
        plugin_id=plugin_id,
        name="Help",
        description="Show available commands.",
        enabled=enabled,
        commands=[
            PluginCommandDefinition(
                name=command_name,
                description="Show available commands.",
                aliases=aliases or [],
                enabled=command_enabled,
            )
        ],
        events=events or [],
        tasks=tasks or [],
    )


def test_plugin_registry_registers_and_lists_plugins() -> None:
    registry = PluginRegistry()
    definition = _definition()
    executor = _FakePluginExecutor()

    registry.register(definition, executor)

    assert registry.exists("builtin.help")
    assert registry.get_definition("builtin.help") is definition
    assert registry.get_executor("builtin.help") is executor
    assert registry.list_definitions() == [definition]
    assert registry.list_commands() == definition.commands
    assert registry.list_statuses()[0].status == PluginLifecycleStatus.ENABLED


def test_plugin_registry_resolves_command_and_alias() -> None:
    registry = PluginRegistry()
    definition = _definition(aliases=["h"])
    executor = _FakePluginExecutor()

    registry.register(definition, executor)

    assert registry.resolve_command("/help") == (
        definition,
        definition.commands[0],
        executor,
    )
    assert registry.resolve_command("H") == (
        definition,
        definition.commands[0],
        executor,
    )


def test_plugin_registry_rejects_duplicate_plugin_ids() -> None:
    registry = PluginRegistry()

    registry.register(_definition(), _FakePluginExecutor())

    with pytest.raises(ConflictError):
        registry.register(_definition(), _FakePluginExecutor())


def test_plugin_registry_rejects_duplicate_commands_and_aliases() -> None:
    registry = PluginRegistry()

    registry.register(_definition(command_name="help"), _FakePluginExecutor())

    with pytest.raises(ConflictError):
        registry.register(
            _definition(plugin_id="builtin.status", command_name="status", aliases=["help"]),
            _FakePluginExecutor(),
        )


def test_plugin_registry_ignores_disabled_plugin_commands() -> None:
    registry = PluginRegistry()

    registry.register(
        _definition(plugin_id="disabled.plugin", enabled=False),
        _FakePluginExecutor(),
    )
    registry.register(
        _definition(plugin_id="disabled.command", command_enabled=False),
        _FakePluginExecutor(),
    )

    assert registry.list_commands() == []
    with pytest.raises(PluginNotFoundError):
        registry.resolve_command("help")


def test_plugin_registry_requires_executor_for_command_resolution() -> None:
    registry = PluginRegistry()

    registry.register(_definition())

    with pytest.raises(PluginStateError):
        registry.resolve_command("help")


def test_plugin_registry_raises_when_plugin_is_missing() -> None:
    registry = PluginRegistry()

    with pytest.raises(PluginNotFoundError):
        registry.get_definition("missing")

    with pytest.raises(PluginNotFoundError):
        registry.get_executor("missing")

    with pytest.raises(PluginNotFoundError):
        registry.unregister("missing")


def test_plugin_registry_unregisters_plugin_and_commands() -> None:
    registry = PluginRegistry()

    registry.register(_definition(), _FakePluginExecutor())
    registry.unregister("builtin.help")

    assert not registry.exists("builtin.help")
    with pytest.raises(PluginNotFoundError):
        registry.resolve_command("help")


def test_plugin_registry_lists_and_resolves_events() -> None:
    registry = PluginRegistry()
    definition = _definition(
        events=[PluginEventDefinition(event_type=PluginEventType.MESSAGE)]
    )
    event_executor = _FakePluginEventExecutor()

    registry.register(
        definition,
        _FakePluginExecutor(),
        event_executor=event_executor,
    )

    event = PluginEvent(
        event_id="event-1",
        event_type=PluginEventType.MESSAGE,
        session_id="session-1",
    )

    assert registry.list_events() == definition.events
    assert registry.resolve_events(event) == [
        (definition, definition.events[0], event_executor)
    ]


def test_plugin_registry_lists_tasks_and_records_status() -> None:
    registry = PluginRegistry()
    definition = _definition(
        tasks=[PluginTaskDefinition(name="follow_up")]
    )

    registry.register(definition, _FakePluginExecutor())
    registry.record_status(
        PluginStatusReport(
            plugin_id=definition.plugin_id,
            status=PluginLifecycleStatus.FAILED,
            reason="setup_failed",
            error="boom",
        )
    )

    assert registry.list_tasks() == definition.tasks
    assert registry.list_statuses()[0].status == PluginLifecycleStatus.FAILED
    assert registry.list_statuses()[0].reason == "setup_failed"
