from __future__ import annotations

from cyreneAI.core.schema.bot import BotCommand
from cyreneAI.core.schema.plugin import (
    PluginCapability,
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginDefinition,
    PluginManifest,
    PluginPermission,
)


def test_plugin_definition_defaults() -> None:
    definition = PluginDefinition(
        plugin_id="builtin.help",
        name="Help",
        description="Show available commands.",
    )

    assert definition.version == "0.1.0"
    assert definition.author is None
    assert definition.license is None
    assert definition.homepage is None
    assert definition.repository is None
    assert definition.keywords == []
    assert definition.capabilities == []
    assert definition.permissions == []
    assert definition.commands == []
    assert definition.enabled is True
    assert definition.builtin is False
    assert definition.metadata == {}


def test_plugin_command_definition_defaults() -> None:
    command = PluginCommandDefinition(
        name="help",
        description="Show available commands.",
    )

    assert command.usage is None
    assert command.aliases == []
    assert command.admin_required is False
    assert command.enabled is True
    assert command.metadata == {}


def test_plugin_command_request_and_result_defaults() -> None:
    request = PluginCommandRequest(
        command=BotCommand(raw_text="/help", name="help"),
    )
    result = PluginCommandResult()

    assert request.event is None
    assert request.is_admin is False
    assert request.metadata == {}
    assert result.handled is True
    assert result.actions == []
    assert result.metadata == {}


def test_plugin_definition_declares_capabilities_and_commands() -> None:
    definition = PluginDefinition(
        plugin_id="builtin.status",
        name="Status",
        description="Show runtime status.",
        builtin=True,
        capabilities=[PluginCapability.BOT_COMMAND, PluginCapability.STATUS],
        permissions=[PluginPermission.PROVIDER_READ],
        commands=[
            PluginCommandDefinition(
                name="status",
                description="Show runtime status.",
                admin_required=True,
            )
        ],
    )

    assert definition.builtin is True
    assert definition.capabilities == [
        PluginCapability.BOT_COMMAND,
        PluginCapability.STATUS,
    ]
    assert definition.permissions == [PluginPermission.PROVIDER_READ]
    assert definition.commands[0].admin_required is True


def test_plugin_manifest_converts_to_definition() -> None:
    command = PluginCommandDefinition(
        name="hello",
        description="Say hello.",
    )
    manifest = PluginManifest(
        plugin_id="thirdparty.hello",
        name="Hello",
        description="Third-party hello plugin.",
        entrypoint="plugin.py",
        author="Cyrene",
        license="MIT",
        homepage="https://example.com",
        repository="https://example.com/repo.git",
        keywords=["demo", "hello"],
        capabilities=[PluginCapability.BOT_COMMAND],
        permissions=[PluginPermission.CHAT],
        commands=[command],
        metadata={"source": "test"},
    )

    definition = manifest.to_definition()

    assert definition.plugin_id == "thirdparty.hello"
    assert definition.name == "Hello"
    assert definition.version == "0.1.0"
    assert definition.author == "Cyrene"
    assert definition.license == "MIT"
    assert definition.homepage == "https://example.com"
    assert definition.repository == "https://example.com/repo.git"
    assert definition.keywords == ["demo", "hello"]
    assert definition.capabilities == [PluginCapability.BOT_COMMAND]
    assert definition.permissions == [PluginPermission.CHAT]
    assert definition.commands == [command]
    assert definition.metadata == {"source": "test"}
