from __future__ import annotations

from cyreneAI.core.schema.bot import BotCommand
from cyreneAI.core.schema.chat import ChatRequest
from cyreneAI.core.schema.message import Message, MessageRole
from cyreneAI.core.schema.plugin import (
    PluginCommandArgumentDefinition,
    PluginCommandArgumentKind,
    PluginLifecycleStatus,
    PluginCapability,
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginDefinition,
    PluginEvent,
    PluginEventDefinition,
    PluginEventRequest,
    PluginEventResult,
    PluginEventType,
    PluginManifest,
    PluginMessageReceipt,
    PluginMiddlewareDefinition,
    PluginMiddlewareRequest,
    PluginMiddlewareType,
    PluginPermission,
    PluginRuntimeCapabilityStatus,
    PluginRuntimeDependencyInfo,
    PluginRuntimePermissionInfo,
    PluginStatusReport,
    PluginTaskDefinition,
    PluginTaskRequest,
    PluginTaskResult,
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
    assert definition.python_dependencies == []
    assert definition.capabilities == []
    assert definition.permissions == []
    assert definition.commands == []
    assert definition.tasks == []
    assert definition.events == []
    assert definition.middlewares == []
    assert definition.enabled is True
    assert definition.builtin is False
    assert definition.metadata == {}


def test_plugin_command_definition_defaults() -> None:
    command = PluginCommandDefinition(
        name="help",
        description="Show available commands.",
    )

    assert command.usage is None
    assert command.arguments == []
    assert command.aliases == []
    assert command.admin_required is False
    assert command.enabled is True
    assert command.metadata == {}


def test_plugin_command_argument_definition_schema() -> None:
    argument = PluginCommandArgumentDefinition(
        name="message",
    )

    assert argument.name == "message"
    assert argument.type == "str"
    assert argument.kind == PluginCommandArgumentKind.POSITIONAL
    assert argument.required is True
    assert argument.default is None
    assert argument.aliases == []
    assert argument.choices == []
    assert argument.description == ""


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


def test_plugin_task_definition_request_and_result_defaults() -> None:
    task = PluginTaskDefinition(
        name="daily",
    )
    request = PluginTaskRequest(task=task)
    result = PluginTaskResult()

    assert task.description == ""
    assert task.interval_seconds is None
    assert task.daily_at is None
    assert task.run_on_start is False
    assert task.enabled is True
    assert task.metadata == {}
    assert request.payload == {}
    assert request.metadata == {}
    assert result.handled is True
    assert result.metadata == {}


def test_plugin_event_definition_request_and_result_defaults() -> None:
    event_definition = PluginEventDefinition(event_type=PluginEventType.MESSAGE)
    event = PluginEvent(
        event_id="event-1",
        event_type=PluginEventType.MESSAGE,
        session_id="session-1",
        user_id="user-1",
        text="hello",
    )
    request = PluginEventRequest(route=event_definition, event=event)
    result = PluginEventResult()

    assert event_definition.description == ""
    assert event_definition.enabled is True
    assert event_definition.metadata == {}
    assert request.event is event
    assert request.metadata == {}
    assert result.handled is True
    assert result.actions == []
    assert result.metadata == {}


def test_plugin_middleware_definition_and_request_schema() -> None:
    definition = PluginMiddlewareDefinition(middleware_type=PluginMiddlewareType.LLM)
    request = PluginMiddlewareRequest(
        route=definition,
        chat_request=ChatRequest(
            provider_id="provider-1",
            model="model",
            messages=[Message(role=MessageRole.USER, content=[])],
        ),
    )

    assert definition.middleware_type == PluginMiddlewareType.LLM
    assert definition.description == ""
    assert definition.enabled is True
    assert definition.metadata == {}
    assert request.route is definition
    assert request.metadata == {}


def test_plugin_message_receipt_defaults() -> None:
    receipt = PluginMessageReceipt(session_id="session-1")

    assert receipt.session_id == "session-1"
    assert receipt.accepted is True
    assert receipt.metadata == {}


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
    task = PluginTaskDefinition(
        name="daily",
        interval_seconds=60,
    )
    event = PluginEventDefinition(
        event_type=PluginEventType.MESSAGE,
        description="Observe messages.",
    )
    middleware = PluginMiddlewareDefinition(
        middleware_type=PluginMiddlewareType.LLM,
        description="Trace LLM calls.",
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
        python_dependencies=["numpy>=2"],
        capabilities=[PluginCapability.BOT_COMMAND],
        permissions=[PluginPermission.LLM, PluginPermission.MESSAGE_SEND],
        commands=[command],
        tasks=[task],
        events=[event],
        middlewares=[middleware],
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
    assert definition.python_dependencies == ["numpy>=2"]
    assert definition.capabilities == [PluginCapability.BOT_COMMAND]
    assert definition.permissions == [
        PluginPermission.LLM,
        PluginPermission.MESSAGE_SEND,
    ]
    assert definition.commands == [command]
    assert definition.tasks == [task]
    assert definition.events == [event]
    assert definition.middlewares == [middleware]
    assert definition.metadata == {"source": "test"}


def test_plugin_runtime_permission_info_schema() -> None:
    info = PluginRuntimePermissionInfo(
        permission=PluginPermission.TOOL,
        status=PluginRuntimeCapabilityStatus.SUPPORTED,
        setup_apis=["register_tool"],
        description="Register tools.",
    )
    dependency = PluginRuntimeDependencyInfo(
        name="storage",
        status=PluginRuntimeCapabilityStatus.SUPPORTED,
        permission=PluginPermission.STORAGE,
    )

    assert info.permission == PluginPermission.TOOL
    assert info.dependencies == []
    assert info.setup_apis == ["register_tool"]
    assert dependency.permission == PluginPermission.STORAGE


def test_plugin_status_report_defaults() -> None:
    status = PluginStatusReport(
        plugin_id="demo.hello",
        status=PluginLifecycleStatus.FAILED,
        reason="setup_failed",
        error="boom",
    )

    assert status.enabled is False
    assert status.name is None
    assert status.version is None
    assert status.reason == "setup_failed"
    assert status.error == "boom"
