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
