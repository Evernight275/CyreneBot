from __future__ import annotations

import asyncio

import pytest

from cyreneAI.application.bootstrap import build_cyrene_ai_runtime
from cyreneAI.core.errors.plugin import (
    PluginAuthorizationError,
    PluginConfigurationError,
)
from cyreneAI.core.schema.bot import BotCommand
from cyreneAI.core.schema.plugin import (
    PluginCapability,
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginManifest,
    PluginPermission,
)
from cyreneAI.core.schema.tool import ToolCall, ToolDefinition, ToolResult


class _HelloExecutor:
    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        return PluginCommandResult(
            metadata={
                "command": request.command.name,
                "args": list(request.command.args),
            }
        )


class _FakeToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content="ok",
        )


class _FakePluginLoader:
    def __init__(self, *modules: object) -> None:
        self._modules = list(modules)

    def load(self) -> list[object]:
        return self._modules


class _HelloPlugin:
    manifest = PluginManifest(
        plugin_id="thirdparty.hello",
        name="Hello",
        description="Third-party hello plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.BOT_COMMAND],
        commands=[
            PluginCommandDefinition(
                name="hello",
                description="Say hello.",
                aliases=["hi"],
            )
        ],
    )

    def __init__(self) -> None:
        self.runtime_context = None

    def setup(self, context) -> None:
        self.runtime_context = context.runtime
        context.register_command(
            PluginCommandDefinition(
                name="hello",
                description="Say hello.",
                aliases=["hi"],
            ),
            _HelloExecutor(),
        )


def test_plugin_host_loads_third_party_command_from_loader() -> None:
    async def run() -> None:
        plugin = _HelloPlugin()
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_manager is not None
            assert runtime.plugin_host is not None
            assert [item.plugin_id for item in runtime.plugin_manager.list_plugins()] == [
                "thirdparty.hello"
            ]
            assert [item.name for item in runtime.plugin_manager.list_commands()] == [
                "hello"
            ]

            result = await runtime.plugin_manager.execute_command(
                PluginCommandRequest(
                    command=BotCommand(
                        raw_text="/hi world",
                        name="hi",
                        args=("world",),
                        args_text="world",
                    )
                )
            )

            assert result.metadata == {
                "command": "hi",
                "args": ["world"],
            }
            assert plugin.runtime_context is not None
            assert not hasattr(plugin.runtime_context, "provider_manager")
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_runtime_context_requires_declared_permission() -> None:
    async def run() -> None:
        plugin = _HelloPlugin()
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            register_builtin_plugins=False,
        )
        try:
            assert plugin.runtime_context is not None
            with pytest.raises(PluginAuthorizationError):
                plugin.runtime_context.list_providers()
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_runtime_context_allows_declared_permission() -> None:
    class ProviderReadPlugin(_HelloPlugin):
        manifest = _HelloPlugin.manifest.model_copy(
            update={
                "plugin_id": "thirdparty.providers",
                "permissions": [PluginPermission.PROVIDER_READ],
            }
        )

    async def run() -> None:
        plugin = ProviderReadPlugin()
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            register_builtin_plugins=False,
        )
        try:
            assert plugin.runtime_context is not None
            assert plugin.runtime_context.list_providers() == []
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_setup_context_requires_tool_permission() -> None:
    class ToolPlugin:
        manifest = PluginManifest(
            plugin_id="thirdparty.tool",
            name="Tool",
            description="Tool plugin.",
            entrypoint="plugin.py",
            capabilities=[PluginCapability.TOOL],
        )

        def setup(self, context) -> None:
            context.register_tool(
                ToolDefinition(name="lookup", description="Lookup value."),
                _FakeToolExecutor(),
            )

    async def run() -> None:
        with pytest.raises(PluginAuthorizationError):
            await build_cyrene_ai_runtime(
                plugin_loaders=[_FakePluginLoader(ToolPlugin())],
                register_builtin_plugins=False,
            )

    asyncio.run(run())


def test_plugin_host_wraps_loader_errors() -> None:
    class BrokenLoader:
        def load(self) -> list[object]:
            raise RuntimeError("boom")

    async def run() -> None:
        with pytest.raises(PluginConfigurationError) as caught:
            await build_cyrene_ai_runtime(
                plugin_loaders=[BrokenLoader()],
                register_builtin_plugins=False,
            )

        assert isinstance(caught.value.cause, RuntimeError)

    asyncio.run(run())


def test_plugin_host_rejects_manifest_command_without_executor() -> None:
    class MissingExecutorPlugin:
        manifest = PluginManifest(
            plugin_id="thirdparty.missing_executor",
            name="Missing Executor",
            description="Broken plugin.",
            entrypoint="plugin.py",
            capabilities=[PluginCapability.BOT_COMMAND],
            commands=[
                PluginCommandDefinition(
                    name="broken",
                    description="Broken command.",
                )
            ],
        )

        def setup(self, context) -> None:
            return None

    async def run() -> None:
        with pytest.raises(PluginConfigurationError):
            await build_cyrene_ai_runtime(
                plugin_loaders=[_FakePluginLoader(MissingExecutorPlugin())],
                register_builtin_plugins=False,
            )

    asyncio.run(run())
