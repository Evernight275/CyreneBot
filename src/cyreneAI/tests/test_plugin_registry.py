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
    PluginMiddlewareDefinition,
    PluginMiddlewareRequest,
    PluginMiddlewareType,
    PluginStatusReport,
    PluginTaskDefinition,
)
from cyreneAI.core.schema.chat import ChatResponse


class _FakePluginExecutor:
    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        return PluginCommandResult(metadata={"command": request.command.name})


class _FakePluginEventExecutor:
    async def execute(self, request: PluginEventRequest) -> PluginEventResult:
        return PluginEventResult(metadata={"event": request.event.event_type})


class _FakePluginMiddlewareExecutor:
    async def execute(self, request: PluginMiddlewareRequest, next_call) -> ChatResponse:
        return await next_call(request)


def _definition(
    plugin_id: str = "builtin.help",
    *,
    command_name: str = "help",
    aliases: list[str] | None = None,
    enabled: bool = True,
    command_enabled: bool = True,
    events: list[PluginEventDefinition] | None = None,
    tasks: list[PluginTaskDefinition] | None = None,
    middlewares: list[PluginMiddlewareDefinition] | None = None,
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
        middlewares=middlewares or [],
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

    with pytest.raises(ConflictError) as caught:
        registry.register(
            _definition(plugin_id="builtin.status", command_name="status", aliases=["help"]),
            _FakePluginExecutor(),
        )
    assert str(caught.value) == "该插件命令 help 已由 builtin.help 注册"


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


def test_plugin_registry_can_disable_and_enable_plugin() -> None:
    registry = PluginRegistry()
    definition = _definition()
    executor = _FakePluginExecutor()
    registry.register(definition, executor)

    disabled = registry.set_enabled("builtin.help", False)

    assert disabled.enabled is False
    assert registry.list_commands() == []
    assert registry.list_statuses()[0].status == PluginLifecycleStatus.DISABLED

    enabled = registry.set_enabled("builtin.help", True)

    assert enabled.enabled is True
    assert registry.resolve_command("help") == (
        enabled,
        enabled.commands[0],
        executor,
    )
    assert registry.list_statuses()[0].status == PluginLifecycleStatus.ENABLED


def test_plugin_registry_refuses_to_enable_plugin_without_executor() -> None:
    registry = PluginRegistry()
    registry.register(_definition(enabled=False))

    with pytest.raises(PluginStateError):
        registry.set_enabled("builtin.help", True)


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


def test_plugin_registry_lists_and_resolves_middlewares() -> None:
    registry = PluginRegistry()
    definition = _definition(
        middlewares=[
            PluginMiddlewareDefinition(middleware_type=PluginMiddlewareType.LLM)
        ]
    )
    middleware_executor = _FakePluginMiddlewareExecutor()

    registry.register(
        definition,
        _FakePluginExecutor(),
        middleware_executor=middleware_executor,
    )

    assert registry.list_middlewares() == definition.middlewares
    assert registry.resolve_middlewares(PluginMiddlewareType.LLM) == [
        (definition, definition.middlewares[0], middleware_executor)
    ]


def test_plugin_registry_resolves_middlewares_in_registration_order() -> None:
    registry = PluginRegistry()
    first = _definition(
        plugin_id="plugin.first",
        command_name="first",
        middlewares=[
            PluginMiddlewareDefinition(middleware_type=PluginMiddlewareType.LLM)
        ],
    )
    second = _definition(
        plugin_id="plugin.second",
        command_name="second",
        middlewares=[
            PluginMiddlewareDefinition(middleware_type=PluginMiddlewareType.LLM)
        ],
    )
    first_executor = _FakePluginMiddlewareExecutor()
    second_executor = _FakePluginMiddlewareExecutor()

    registry.register(
        first,
        _FakePluginExecutor(),
        middleware_executor=first_executor,
    )
    registry.register(
        second,
        _FakePluginExecutor(),
        middleware_executor=second_executor,
    )

    assert registry.resolve_middlewares(PluginMiddlewareType.LLM) == [
        (first, first.middlewares[0], first_executor),
        (second, second.middlewares[0], second_executor),
    ]


def test_plugin_registry_skips_disabled_plugin_and_middleware() -> None:
    registry = PluginRegistry()
    disabled_plugin = _definition(
        plugin_id="plugin.disabled",
        command_name="disabled",
        enabled=False,
        middlewares=[
            PluginMiddlewareDefinition(middleware_type=PluginMiddlewareType.LLM)
        ],
    )
    disabled_middleware = _definition(
        plugin_id="middleware.disabled",
        command_name="middleware-disabled",
        middlewares=[
            PluginMiddlewareDefinition(
                middleware_type=PluginMiddlewareType.LLM,
                enabled=False,
            )
        ],
    )
    enabled = _definition(
        plugin_id="middleware.enabled",
        command_name="middleware-enabled",
        middlewares=[
            PluginMiddlewareDefinition(middleware_type=PluginMiddlewareType.LLM)
        ],
    )
    enabled_executor = _FakePluginMiddlewareExecutor()

    registry.register(
        disabled_plugin,
        _FakePluginExecutor(),
        middleware_executor=_FakePluginMiddlewareExecutor(),
    )
    registry.register(
        disabled_middleware,
        _FakePluginExecutor(),
        middleware_executor=_FakePluginMiddlewareExecutor(),
    )
    registry.register(
        enabled,
        _FakePluginExecutor(),
        middleware_executor=enabled_executor,
    )

    assert registry.list_middlewares() == enabled.middlewares
    assert registry.resolve_middlewares(PluginMiddlewareType.LLM) == [
        (enabled, enabled.middlewares[0], enabled_executor)
    ]
