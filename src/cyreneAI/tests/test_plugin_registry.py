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
)


class _FakePluginExecutor:
    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        return PluginCommandResult(metadata={"command": request.command.name})


def _definition(
    plugin_id: str = "builtin.help",
    *,
    command_name: str = "help",
    aliases: list[str] | None = None,
    enabled: bool = True,
    command_enabled: bool = True,
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
