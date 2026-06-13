from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from cyreneAI.application.bootstrap import build_cyrene_ai_runtime
from cyreneAI.application.plugins.builtin_bot_commands import (
    BUILTIN_BOT_COMMANDS_PLUGIN_ID,
)
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.errors.base import NotFoundError
from cyreneAI.core.errors.plugin import PluginInputError
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.bot import BotCommand, BotEvent, BotEventType, BotMessage
from cyreneAI.core.schema.context import (
    ContextItem,
    ContextItemSource,
    ContextItemType,
    ContextSegment,
    ContextSegmentRole,
    ContextSnapshot,
    ContextWindow,
)
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginCommandArgumentDefinition,
    PluginCommandArgumentKind,
    PluginCommandRequest,
    PluginCommandResult,
    PluginDefinition,
    PluginLifecycleStatus,
    PluginStatusReport,
)
from cyreneAI.core.schema.provider import (
    ProviderCapability,
    ProviderConfig,
    ProviderInfo,
    ProviderModel,
    ProviderType,
)
from cyreneAI.core.schema.tool import ToolDefinition, ToolResult
from cyreneAI.core.tool.registry import ToolRegistry
from cyreneAI.infra.adapters.bot_sessions.memory import InMemoryBotSessionStore


class FakeContextStore:
    def __init__(self) -> None:
        self.snapshots: dict[str, ContextSnapshot] = {}

    async def save_snapshot(self, snapshot: ContextSnapshot) -> None:
        self.snapshots[snapshot.snapshot_id] = snapshot

    async def get_snapshot(self, snapshot_id: str) -> ContextSnapshot:
        return self.snapshots[snapshot_id]

    async def list_snapshots(self, session_id: str) -> list[ContextSnapshot]:
        return [
            snapshot
            for snapshot in self.snapshots.values()
            if snapshot.session_id == session_id
        ]

    async def delete_snapshot(self, snapshot_id: str) -> None:
        self.snapshots.pop(snapshot_id, None)

    async def delete_snapshots_for_session(self, session_id: str) -> int:
        snapshot_ids = [
            snapshot.snapshot_id
            for snapshot in self.snapshots.values()
            if snapshot.session_id == session_id
        ]
        for snapshot_id in snapshot_ids:
            self.snapshots.pop(snapshot_id, None)
        return len(snapshot_ids)


class FakePluginExecutor:
    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        return PluginCommandResult()


class FakeToolExecutor:
    async def execute(self, call) -> ToolResult:
        return ToolResult(call_id=call.id, name=call.name, content="ok")


class FakeProvider:
    info = ProviderInfo(
        provider_type=ProviderType.OPENAI_RESPONSES,
        name="Fake Provider",
        description="Fake provider.",
        models=["catalog-model"],
        capabilities=[ProviderCapability.CHAT],
    )

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self.closed = False

    async def list_models(self) -> list[ProviderModel]:
        return [ProviderModel(model_id="runtime-model")]

    async def close(self) -> None:
        self.closed = True


class FakeProviderConfigStore:
    def __init__(self, *configs: ProviderConfig) -> None:
        self.configs = {config.provider_id: config for config in configs}
        self.upserted: list[ProviderConfig] = []

    async def list_configs(self) -> list[ProviderConfig]:
        return list(self.configs.values())

    async def get_config(self, provider_id: str) -> ProviderConfig:
        config = self.configs.get(provider_id)
        if config is None:
            raise NotFoundError(f"Provider config not found: {provider_id}")
        return config

    async def upsert_config(self, config: ProviderConfig) -> None:
        self.configs[config.provider_id] = config
        self.upserted.append(config)

    async def delete_config(self, provider_id: str) -> None:
        self.configs.pop(provider_id, None)

    async def close(self) -> None:
        pass


def _event(text: str) -> BotEvent:
    return BotEvent(
        event_id="event-1",
        event_type=BotEventType.COMMAND,
        channel_id="memory",
        session_id="memory:user-1",
        user_id="user-1",
        message=BotMessage(
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=text,
                )
            ]
        ),
    )


async def _provider_runtime(
    *,
    config_store: FakeProviderConfigStore | None = None,
    provider_configs: list[ProviderConfig] | None = None,
):
    provider_registry = ProviderRegistry()
    provider_registry.register_provider(FakeProvider.info)
    provider_factory = ProviderFactory()
    provider_factory.register(
        ProviderType.OPENAI_RESPONSES,
        lambda config: _build_fake_provider(config),
    )
    provider_manager = ProviderManager(provider_factory)
    for config in provider_configs or []:
        if config.enabled:
            await provider_manager.add(config)
    return await build_cyrene_ai_runtime(
        provider_manager=provider_manager,
        provider_registry=provider_registry,
        provider_config_store=config_store,
    )


async def _build_fake_provider(config: ProviderConfig) -> FakeProvider:
    return FakeProvider(config)


def _text(result: PluginCommandResult) -> str:
    assert result.actions[0].message is not None
    return result.actions[0].message.content[0].text or ""


def test_builtin_bot_command_plugin_is_registered_by_default() -> None:
    async def run() -> None:
        runtime = await build_cyrene_ai_runtime()

        assert runtime.plugin_manager is not None
        plugins = runtime.plugin_manager.list_plugins()
        assert plugins[0].plugin_id == BUILTIN_BOT_COMMANDS_PLUGIN_ID
        assert [command.name for command in runtime.plugin_manager.list_commands()] == [
            "start",
            "help",
            "ping",
            "echo",
            "session",
            "session current",
            "session status",
            "session ls",
            "session new",
            "session use",
            "session rename",
            "session clear",
            "session delete",
            "reset",
            "status",
            "agent runs",
            "agent run",
            "agent trace",
            "tool ls",
            "tool on",
            "tool off",
            "tool off_all",
            "provider ls",
            "provider catalog",
            "provider status",
            "provider models",
            "provider start",
            "provider stop",
            "provider reload",
            "provider check",
            "plugin ls",
            "plugin commands",
            "plugin status",
        ]

        await runtime.close()

    asyncio.run(run())


def test_builtin_bot_command_plugin_can_be_disabled() -> None:
    async def run() -> None:
        runtime = await build_cyrene_ai_runtime(register_builtin_plugins=False)

        assert runtime.plugin_manager is not None
        assert runtime.plugin_manager.list_plugins() == []
        assert runtime.plugin_manager.list_commands() == []

        await runtime.close()

    asyncio.run(run())


def test_builtin_basic_commands_require_event_and_render_common_replies() -> None:
    async def run() -> None:
        runtime = await build_cyrene_ai_runtime(register_builtin_tools=False)
        assert runtime.plugin_manager is not None

        with pytest.raises(PluginInputError, match="bot event"):
            await runtime.plugin_manager.execute_command(
                PluginCommandRequest(
                    command=BotCommand(raw_text="/ping", name="ping"),
                )
            )

        start = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/start", name="start"),
                event=_event("/start"),
            )
        )
        ping = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/ping", name="ping"),
                event=_event("/ping"),
            )
        )
        empty_echo = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/echo", name="echo"),
                event=_event("/echo"),
            )
        )
        echo = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/echo hello world",
                    name="echo",
                    args=("hello", "world"),
                    args_text="hello world",
                ),
                event=_event("/echo hello world"),
            )
        )

        assert _text(start) == "\n".join(
            [
                "CyreneAI bot is ready.",
                "Use /help to see available commands.",
            ]
        )
        assert start.metadata == {
            "plugin_id": BUILTIN_BOT_COMMANDS_PLUGIN_ID,
            "command": "start",
            "command_args": [],
        }
        assert start.actions[0].metadata["bot_event_id"] == "event-1"
        assert _text(ping) == "pong"
        assert _text(empty_echo) == "(empty)"
        assert _text(echo) == "hello world"

        await runtime.close()

    asyncio.run(run())


def test_builtin_help_command_lists_registered_commands() -> None:
    async def run() -> None:
        runtime = await build_cyrene_ai_runtime()
        assert runtime.plugin_manager is not None

        result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/help", name="help"),
                event=_event("/help"),
            )
        )

        assert result.actions[0].message is not None
        text = result.actions[0].message.content[0].text
        assert text == "\n".join(
            [
                "Available commands:",
                "Built-in:",
                "/start - Start the bot.",
                "/help - Show available commands.",
                "/ping - Check whether the bot is responsive.",
                "/echo <text> - Echo text back.",
                "/session - Show current session.",
                "/session current - Show current session.",
                "/session status <name> - Show session status.",
                "/session ls - List sessions.",
                "/session new <name> - Create and select a session.",
                "/session use <name> - Select a session.",
                "/session rename <old> <new> - Rename a session.",
                "/session clear <name> - Clear session context.",
                "/session delete <name> - Delete a session.",
                "/reset [session] - Reset current session context.",
            ]
        )

        await runtime.close()

    asyncio.run(run())


def test_builtin_session_commands_report_disabled_usage_and_lookup_errors() -> None:
    async def run() -> None:
        disabled_runtime = await build_cyrene_ai_runtime()
        assert disabled_runtime.plugin_manager is not None
        disabled = await disabled_runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/session", name="session"),
                event=_event("/session"),
            )
        )
        await disabled_runtime.close()

        runtime = await build_cyrene_ai_runtime(
            bot_session_manager=BotSessionManager(InMemoryBotSessionStore()),
        )
        assert runtime.plugin_manager is not None
        event = _event("/session")
        commands = [
            BotCommand(raw_text="/session status", name="session status"),
            BotCommand(raw_text="/session new", name="session new"),
            BotCommand(raw_text="/session use", name="session use"),
            BotCommand(
                raw_text="/session rename old",
                name="session rename",
                args=("old",),
                args_text="old",
            ),
            BotCommand(raw_text="/session clear", name="session clear"),
            BotCommand(raw_text="/session delete", name="session delete"),
        ]
        usage_results = [
            await runtime.plugin_manager.execute_command(
                PluginCommandRequest(command=command, event=event)
            )
            for command in commands
        ]
        missing_status = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/session status missing",
                    name="session status",
                    args=("missing",),
                    args_text="missing",
                ),
                event=event,
            )
        )

        assert _text(disabled) == "Bot sessions are disabled."
        assert [_text(result) for result in usage_results] == [
            "Usage: /session status <name>",
            "Usage: /session new <name>",
            "Usage: /session use <name>",
            "Usage: /session rename <old> <new>",
            "Usage: /session clear <name>",
            "Usage: /session delete <name>",
        ]
        assert _text(missing_status).startswith("Session status failed:")

        await runtime.close()

    asyncio.run(run())


def test_builtin_session_commands_manage_conversations_and_reset_context() -> None:
    async def run() -> None:
        store = FakeContextStore()
        runtime = await build_cyrene_ai_runtime(
            bot_session_manager=BotSessionManager(InMemoryBotSessionStore()),
            context_manager=ContextManager(store),
        )
        assert runtime.plugin_manager is not None

        event = _event("/session")
        current = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/session", name="session"),
                event=event,
            )
        )
        created = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/session new work",
                    name="session new",
                    args=("work",),
                    args_text="work",
                ),
                event=event,
            )
        )
        listed = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/session ls", name="session ls"),
                event=event,
            )
        )
        default_status = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/session status default",
                    name="session status",
                    args=("default",),
                    args_text="default",
                ),
                event=event,
            )
        )
        selected_default = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/session use default",
                    name="session use",
                    args=("default",),
                    args_text="default",
                ),
                event=event,
            )
        )

        default_session_id = "memory:user-1:conversation:default"
        work_session_id = "memory:user-1:conversation:work"
        await store.save_snapshot(
            ContextSnapshot(
                snapshot_id="default-snapshot",
                session_id=default_session_id,
                window=ContextWindow(window_id="default-window"),
            )
        )
        await store.save_snapshot(
            ContextSnapshot(
                snapshot_id="work-snapshot",
                session_id=work_session_id,
                window=ContextWindow(window_id="work-window"),
            )
        )

        reset_default = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/reset default",
                    name="reset",
                    args=("default",),
                    args_text="default",
                ),
                event=event,
            )
        )
        selected_work = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/session use work",
                    name="session use",
                    args=("work",),
                    args_text="work",
                ),
                event=event,
            )
        )
        renamed = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/session rename work work notes",
                    name="session rename",
                    args=("work", "work", "notes"),
                    args_text="work work notes",
                ),
                event=event,
            )
        )
        deleted = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/session delete work notes",
                    name="session delete",
                    args=("work", "notes"),
                    args_text="work notes",
                ),
                event=event,
            )
        )

        assert current.actions[0].message is not None
        assert current.actions[0].message.content[0].text == "\n".join(
            [
                "Session default:",
                "status: active",
                "id: default",
                "context_session_id: memory:user-1:conversation:default",
            ]
        )
        assert created.actions[0].message is not None
        assert created.actions[0].message.content[0].text == (
            "Session work created and selected."
        )
        assert listed.actions[0].message is not None
        assert listed.actions[0].message.content[0].text == "\n".join(
            [
                "Sessions:",
                (
                    "- default id=default status=inactive "
                    "context_session_id=memory:user-1:conversation:default"
                ),
                (
                    "- work id=work status=active "
                    "context_session_id=memory:user-1:conversation:work"
                ),
            ]
        )
        assert default_status.actions[0].message is not None
        assert default_status.actions[0].message.content[0].text == "\n".join(
            [
                "Session default:",
                "status: inactive",
                "id: default",
                "context_session_id: memory:user-1:conversation:default",
            ]
        )
        assert selected_default.actions[0].message is not None
        assert selected_default.actions[0].message.content[0].text == (
            "Session default selected."
        )
        assert reset_default.actions[0].message is not None
        assert reset_default.actions[0].message.content[0].text == (
            "Session default reset. Context snapshots deleted: 1."
        )
        assert selected_work.actions[0].message is not None
        assert selected_work.actions[0].message.content[0].text == (
            "Session work selected."
        )
        assert renamed.actions[0].message is not None
        assert renamed.actions[0].message.content[0].text == (
            "Session renamed to work notes."
        )
        assert deleted.actions[0].message is not None
        assert deleted.actions[0].message.content[0].text == (
            "Session work notes deleted. Context snapshots deleted: 1."
        )
        assert await store.list_snapshots(default_session_id) == []
        assert await store.list_snapshots(work_session_id) == []

        await runtime.close()

    asyncio.run(run())


def test_builtin_session_clear_keeps_conversation() -> None:
    async def run() -> None:
        store = FakeContextStore()
        runtime = await build_cyrene_ai_runtime(
            bot_session_manager=BotSessionManager(InMemoryBotSessionStore()),
            context_manager=ContextManager(store),
        )
        assert runtime.plugin_manager is not None

        event = _event("/session")
        await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/session new work",
                    name="session new",
                    args=("work",),
                    args_text="work",
                ),
                event=event,
            )
        )
        work_session_id = "memory:user-1:conversation:work"
        await store.save_snapshot(
            ContextSnapshot(
                snapshot_id="work-snapshot",
                session_id=work_session_id,
                window=ContextWindow(window_id="work-window"),
            )
        )

        cleared = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/session clear work",
                    name="session clear",
                    args=("work",),
                    args_text="work",
                ),
                event=event,
            )
        )
        listed = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/session ls", name="session ls"),
                event=event,
            )
        )

        assert cleared.actions[0].message is not None
        assert cleared.actions[0].message.content[0].text == (
            "Session work cleared. Context snapshots deleted: 1."
        )
        assert await store.list_snapshots(work_session_id) == []
        assert listed.actions[0].message is not None
        assert (
            "- work id=work status=active "
            "context_session_id=memory:user-1:conversation:work"
        ) in (listed.actions[0].message.content[0].text)

        await runtime.close()

    asyncio.run(run())


def test_builtin_reset_without_session_manager_uses_metadata_session_id() -> None:
    async def run() -> None:
        store = FakeContextStore()
        runtime = await build_cyrene_ai_runtime(
            context_manager=ContextManager(store),
        )
        assert runtime.plugin_manager is not None
        await store.save_snapshot(
            ContextSnapshot(
                snapshot_id="metadata-snapshot",
                session_id="ctx-1",
                window=ContextWindow(window_id="window-1"),
            )
        )

        result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/reset", name="reset"),
                event=_event("/reset"),
                metadata={"context_session_id": "ctx-1"},
            )
        )

        assert _text(result) == "Context reset. Context snapshots deleted: 1."
        assert await store.list_snapshots("ctx-1") == []

        await runtime.close()

    asyncio.run(run())


def test_builtin_reset_command_reports_missing_context_manager() -> None:
    async def run() -> None:
        runtime = await build_cyrene_ai_runtime(
            bot_session_manager=BotSessionManager(InMemoryBotSessionStore()),
        )
        assert runtime.plugin_manager is not None

        result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/reset", name="reset"),
                event=_event("/reset"),
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == (
            "Context manager is not configured."
        )

        await runtime.close()

    asyncio.run(run())


def test_builtin_agent_commands_report_usage_and_not_found() -> None:
    async def run() -> None:
        store = FakeContextStore()
        runtime = await build_cyrene_ai_runtime(
            context_manager=ContextManager(store),
        )
        assert runtime.plugin_manager is not None

        missing_run_id = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/agent run", name="agent run"),
                event=_event("/agent run"),
                is_admin=True,
            )
        )
        too_many_run_args = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/agent runs one two three",
                    name="agent runs",
                    args=("one", "two", "three"),
                    args_text="one two three",
                ),
                event=_event("/agent runs one two three"),
                is_admin=True,
            )
        )
        missing_trace = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/agent trace", name="agent trace"),
                event=_event("/agent trace"),
                is_admin=True,
            )
        )

        assert _text(missing_run_id) == "Usage: /agent run <snapshot_id>"
        assert _text(too_many_run_args) == (
            "Agent runs failed: Usage: /agent runs [session] [limit]"
        )
        assert _text(missing_trace) == (
            "No agent trace found for session memory:user-1."
        )

        await runtime.close()

    asyncio.run(run())


def test_builtin_agent_trace_command_shows_latest_trace_summary() -> None:
    async def run() -> None:
        store = FakeContextStore()
        runtime = await build_cyrene_ai_runtime(
            bot_session_manager=BotSessionManager(InMemoryBotSessionStore()),
            context_manager=ContextManager(store),
        )
        assert runtime.plugin_manager is not None
        session_id = "memory:user-1:conversation:default"
        await store.save_snapshot(
            ContextSnapshot(
                snapshot_id="agent-snapshot",
                session_id=session_id,
                window=ContextWindow(
                    window_id="agent-window",
                    segments=[
                        ContextSegment(
                            segment_id="agent-trace",
                            role=ContextSegmentRole.WORKING,
                            items=[
                                ContextItem(
                                    item_id="trace-1",
                                    type=ContextItemType.TOOL_TRACE,
                                    source=ContextItemSource.TOOL,
                                    metadata={"agent_trace_index": 0},
                                ),
                                ContextItem(
                                    item_id="trace-2",
                                    type=ContextItemType.MESSAGE,
                                    source=ContextItemSource.ASSISTANT,
                                    message=Message(
                                        role=MessageRole.ASSISTANT,
                                        content=[
                                            ContentPart(
                                                type=ContentPartType.TEXT,
                                                text="final answer",
                                            )
                                        ],
                                    ),
                                    metadata={"agent_trace_index": 1},
                                ),
                            ],
                        )
                    ],
                ),
                metadata={
                    "agent_loop": "minimal",
                    "finished_at": "2026-06-04T00:00:00+00:00",
                    "completed": True,
                    "stop_reason": "final_response",
                    "step_count": 2,
                    "tool_call_count": 1,
                    "tool_result_count": 1,
                    "tool_error_count": 0,
                    "tool_names": ["lookup"],
                },
            )
        )

        result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/agent trace", name="agent trace"),
                event=_event("/agent trace"),
                is_admin=True,
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "\n".join(
            [
                "Agent trace:",
                "session_id: memory:user-1:conversation:default",
                "snapshot_id: agent-snapshot",
                "finished_at: 2026-06-04T00:00:00+00:00",
                "completed: true",
                "stop_reason: final_response",
                "steps: 2",
                "tool_calls: 1",
                "tool_results: 1",
                "tool_errors: 0",
                "tools: lookup",
                "trace_items: 2",
                "last_assistant: final answer",
                "trace:",
                "- 0 tool name=- tool_call_id=-: -",
                "- 1 assistant name=- tool_call_id=-: final answer",
            ]
        )

        await runtime.close()

    asyncio.run(run())


def test_builtin_agent_runs_command_lists_active_and_named_session_runs() -> None:
    async def run() -> None:
        store = FakeContextStore()
        runtime = await build_cyrene_ai_runtime(
            bot_session_manager=BotSessionManager(InMemoryBotSessionStore()),
            context_manager=ContextManager(store),
        )
        assert runtime.plugin_manager is not None
        event = _event("/agent runs")
        default_session_id = "memory:user-1:conversation:default"
        work_session_id = "memory:user-1:conversation:work"

        await store.save_snapshot(
            ContextSnapshot(
                snapshot_id="plain-snapshot",
                session_id=default_session_id,
                window=ContextWindow(window_id="plain-window"),
            )
        )
        await store.save_snapshot(
            ContextSnapshot(
                snapshot_id="default-run",
                session_id=default_session_id,
                window=ContextWindow(window_id="default-window"),
                metadata={
                    "agent_loop": "minimal",
                    "completed": True,
                    "stop_reason": "final_response",
                    "step_count": 1,
                    "tool_call_count": 0,
                    "tool_error_count": 0,
                },
            )
        )
        active_result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/agent runs", name="agent runs"),
                event=event,
                is_admin=True,
            )
        )

        await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/session new work",
                    name="session new",
                    args=("work",),
                    args_text="work",
                ),
                event=event,
            )
        )
        await store.save_snapshot(
            ContextSnapshot(
                snapshot_id="work-run",
                session_id=work_session_id,
                window=ContextWindow(window_id="work-window"),
                metadata={
                    "agent_loop": "minimal",
                    "completed": False,
                    "stop_reason": "max_steps",
                    "step_count": 5,
                    "tool_call_count": 2,
                    "tool_error_count": 1,
                    "tool_names": ["lookup", "search"],
                },
            )
        )
        named_result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/agent runs work 5",
                    name="agent runs",
                    args=("work", "5"),
                    args_text="work 5",
                ),
                event=event,
                is_admin=True,
            )
        )

        assert active_result.actions[0].message is not None
        assert active_result.actions[0].message.content[0].text == "\n".join(
            [
                "Agent runs:",
                "session_id: memory:user-1:conversation:default",
                "limit: 10",
                (
                    "- default-run status=final_response completed=true "
                    "steps=1 tool_calls=0 tool_errors=0 tools=-"
                ),
            ]
        )
        assert named_result.actions[0].message is not None
        assert named_result.actions[0].message.content[0].text == "\n".join(
            [
                "Agent runs:",
                "session_id: memory:user-1:conversation:work",
                "limit: 5",
                (
                    "- work-run status=max_steps completed=false "
                    "steps=5 tool_calls=2 tool_errors=1 tools=lookup,search"
                ),
            ]
        )

        await runtime.close()

    asyncio.run(run())


def test_builtin_agent_run_command_shows_compact_trace_detail() -> None:
    async def run() -> None:
        store = FakeContextStore()
        runtime = await build_cyrene_ai_runtime(
            context_manager=ContextManager(store),
        )
        assert runtime.plugin_manager is not None
        await store.save_snapshot(
            ContextSnapshot(
                snapshot_id="run-1",
                session_id="session-1",
                window=ContextWindow(
                    window_id="agent-window",
                    segments=[
                        ContextSegment(
                            segment_id="agent-trace",
                            role=ContextSegmentRole.WORKING,
                            items=[
                                ContextItem(
                                    item_id="trace-1",
                                    type=ContextItemType.TOOL_TRACE,
                                    source=ContextItemSource.TOOL,
                                    content="tool output",
                                    metadata={"agent_trace_index": 0},
                                ),
                            ],
                        )
                    ],
                ),
                metadata={
                    "agent_loop": "minimal",
                    "finished_at": "2026-06-04T00:00:00+00:00",
                    "completed": True,
                    "stop_reason": "final_response",
                    "step_count": 1,
                    "tool_call_count": 1,
                    "tool_result_count": 1,
                    "tool_error_count": 0,
                    "tool_names": ["lookup"],
                },
            )
        )

        result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/agent run run-1",
                    name="agent run",
                    args=("run-1",),
                    args_text="run-1",
                ),
                event=_event("/agent run run-1"),
                is_admin=True,
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "\n".join(
            [
                "Agent run:",
                "session_id: session-1",
                "snapshot_id: run-1",
                "finished_at: 2026-06-04T00:00:00+00:00",
                "completed: true",
                "stop_reason: final_response",
                "steps: 1",
                "tool_calls: 1",
                "tool_results: 1",
                "tool_errors: 0",
                "tools: lookup",
                "trace_items: 1",
                "trace:",
                "- 0 tool name=- tool_call_id=-: tool output",
            ]
        )

        await runtime.close()

    asyncio.run(run())


def test_builtin_agent_runs_command_reports_history_errors() -> None:
    async def run() -> None:
        runtime_without_context = await build_cyrene_ai_runtime()
        assert runtime_without_context.plugin_manager is not None
        missing_context = await runtime_without_context.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/agent runs", name="agent runs"),
                event=_event("/agent runs"),
                is_admin=True,
            )
        )
        await runtime_without_context.close()

        store = FakeContextStore()
        runtime = await build_cyrene_ai_runtime(
            context_manager=ContextManager(store),
        )
        assert runtime.plugin_manager is not None
        no_runs = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/agent runs", name="agent runs"),
                event=_event("/agent runs"),
                is_admin=True,
            )
        )
        invalid_limit = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/agent runs 0",
                    name="agent runs",
                    args=("0",),
                    args_text="0",
                ),
                event=_event("/agent runs 0"),
                is_admin=True,
            )
        )
        invalid_limit_text = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/agent runs session-x nope",
                    name="agent runs",
                    args=("session-x", "nope"),
                    args_text="session-x nope",
                ),
                event=_event("/agent runs session-x nope"),
                is_admin=True,
            )
        )

        assert missing_context.actions[0].message is not None
        assert missing_context.actions[0].message.content[0].text == (
            "Agent runs failed: Context manager is not configured."
        )
        assert no_runs.actions[0].message is not None
        assert no_runs.actions[0].message.content[0].text == (
            "No agent runs found for session memory:user-1."
        )
        assert invalid_limit.actions[0].message is not None
        assert invalid_limit.actions[0].message.content[0].text == (
            "Agent runs failed: Agent run history limit must be between 1 and 50."
        )
        assert invalid_limit_text.actions[0].message is not None
        assert invalid_limit_text.actions[0].message.content[0].text == (
            "Agent runs failed: Agent runs limit must be a number."
        )

        await runtime.close()

    asyncio.run(run())


def test_builtin_tool_commands_report_disabled_empty_usage_and_toggle_states() -> None:
    async def run() -> None:
        disabled_runtime = await build_cyrene_ai_runtime(register_builtin_tools=False)
        disabled_runtime.tool_registry = None
        assert disabled_runtime.plugin_manager is not None
        disabled = await disabled_runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/tool ls", name="tool ls"),
                event=_event("/tool ls"),
                is_admin=True,
            )
        )
        await disabled_runtime.close()

        empty_runtime = await build_cyrene_ai_runtime(register_builtin_tools=False)
        assert empty_runtime.plugin_manager is not None
        empty = await empty_runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/tool ls", name="tool ls"),
                event=_event("/tool ls"),
                is_admin=True,
            )
        )
        usage_on = await empty_runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/tool on", name="tool on"),
                event=_event("/tool on"),
                is_admin=True,
            )
        )
        unknown = await empty_runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/tool off missing",
                    name="tool off",
                    args=("missing",),
                    args_text="missing",
                ),
                event=_event("/tool off missing"),
                is_admin=True,
            )
        )
        await empty_runtime.close()

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="lookup",
                description="Lookup data.",
                metadata={"source": "test"},
            ),
            FakeToolExecutor(),
        )
        runtime = await build_cyrene_ai_runtime(
            tool_registry=registry,
            register_builtin_tools=False,
        )
        assert runtime.plugin_manager is not None
        listed = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/tool ls", name="tool ls"),
                event=_event("/tool ls"),
                is_admin=True,
            )
        )
        off = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/tool off lookup",
                    name="tool off",
                    args=("lookup",),
                    args_text="lookup",
                ),
                event=_event("/tool off lookup"),
                is_admin=True,
            )
        )
        all_off = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/tool off_all", name="tool off_all"),
                event=_event("/tool off_all"),
                is_admin=True,
            )
        )
        on = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/tool on lookup",
                    name="tool on",
                    args=("lookup",),
                    args_text="lookup",
                ),
                event=_event("/tool on lookup"),
                is_admin=True,
            )
        )

        assert _text(disabled) == "Tools are disabled."
        assert _text(empty) == "No tools registered."
        assert _text(usage_on) == "Usage: /tool on <name>"
        assert _text(unknown) == "Unknown tool: missing"
        assert _text(listed) == "\n".join(
            [
                "Tools:",
                "- lookup [on] risk=trusted source=test: Lookup data.",
            ]
        )
        assert _text(off) == "Tool lookup disabled."
        assert _text(all_off) == "Disabled 0 tool(s)."
        assert _text(on) == "Tool lookup enabled."

        await runtime.close()

    asyncio.run(run())


def test_builtin_provider_commands_report_empty_usage_and_missing_runtime() -> None:
    async def run() -> None:
        runtime = await build_cyrene_ai_runtime()
        assert runtime.plugin_manager is not None

        commands = [
            BotCommand(raw_text="/provider ls", name="provider ls"),
            BotCommand(raw_text="/provider catalog", name="provider catalog"),
            BotCommand(raw_text="/provider status", name="provider status"),
            BotCommand(raw_text="/provider models", name="provider models"),
            BotCommand(raw_text="/provider start", name="provider start"),
            BotCommand(
                raw_text="/provider start missing",
                name="provider start",
                args=("missing",),
                args_text="missing",
            ),
            BotCommand(raw_text="/provider stop", name="provider stop"),
            BotCommand(raw_text="/provider reload", name="provider reload"),
            BotCommand(raw_text="/provider check", name="provider check"),
        ]

        results = [
            await runtime.plugin_manager.execute_command(
                PluginCommandRequest(
                    command=command,
                    event=_event(command.raw_text),
                    is_admin=True,
                )
            )
            for command in commands
        ]

        assert [_text(result) for result in results] == [
            "No providers configured.",
            "Provider catalog is not configured.",
            "Usage: /provider status <provider_id>",
            "Usage: /provider models <provider_id>",
            "Usage: /provider start <provider_id>",
            "Provider config store is not configured.",
            "Usage: /provider stop <provider_id>",
            "Usage: /provider reload <provider_id>",
            "Usage: /provider check <provider_id>",
        ]

        await runtime.close()

    asyncio.run(run())


def test_builtin_provider_commands_manage_saved_and_running_providers() -> None:
    async def run() -> None:
        running_config = ProviderConfig(
            provider_id="running",
            provider_type=ProviderType.OPENAI_RESPONSES,
            api_key="secret",
            base_url="https://provider.test",
            timeout=timedelta(seconds=2),
        )
        saved_config = ProviderConfig(
            provider_id="saved",
            provider_type=ProviderType.OPENAI_RESPONSES,
            enabled=False,
            models=[ProviderModel(model_id="saved-model")],
        )
        store = FakeProviderConfigStore(running_config, saved_config)
        runtime = await _provider_runtime(
            config_store=store,
            provider_configs=[running_config],
        )
        assert runtime.plugin_manager is not None

        listed = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/provider ls", name="provider ls"),
                event=_event("/provider ls"),
                is_admin=True,
            )
        )
        catalog = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/provider catalog",
                    name="provider catalog",
                ),
                event=_event("/provider catalog"),
                is_admin=True,
            )
        )
        status = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/provider status running",
                    name="provider status",
                    args=("running",),
                    args_text="running",
                ),
                event=_event("/provider status running"),
                is_admin=True,
            )
        )
        saved_status = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/provider status saved",
                    name="provider status",
                    args=("saved",),
                    args_text="saved",
                ),
                event=_event("/provider status saved"),
                is_admin=True,
            )
        )
        models = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/provider models running",
                    name="provider models",
                    args=("running",),
                    args_text="running",
                ),
                event=_event("/provider models running"),
                is_admin=True,
            )
        )
        check = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/provider check running",
                    name="provider check",
                    args=("running",),
                    args_text="running",
                ),
                event=_event("/provider check running"),
                is_admin=True,
            )
        )
        started = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/provider start saved",
                    name="provider start",
                    args=("saved",),
                    args_text="saved",
                ),
                event=_event("/provider start saved"),
                is_admin=True,
            )
        )
        reloaded = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/provider reload saved",
                    name="provider reload",
                    args=("saved",),
                    args_text="saved",
                ),
                event=_event("/provider reload saved"),
                is_admin=True,
            )
        )
        stopped = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/provider stop running",
                    name="provider stop",
                    args=("running",),
                    args_text="running",
                ),
                event=_event("/provider stop running"),
                is_admin=True,
            )
        )
        unknown = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/provider status missing",
                    name="provider status",
                    args=("missing",),
                    args_text="missing",
                ),
                event=_event("/provider status missing"),
                is_admin=True,
            )
        )

        listed_text = _text(listed)
        assert listed_text.startswith("Providers:")
        assert (
            "- running type=openai_responses status=running enabled=true "
            "configured=true api_key=set"
        ) in listed_text
        assert (
            "- saved type=openai_responses status=stopped enabled=false "
            "configured=true api_key=missing"
        ) in listed_text
        assert _text(catalog) == "\n".join(
            [
                "Provider catalog:",
                "- openai_responses name=Fake Provider capabilities=chat",
            ]
        )
        assert _text(status) == "\n".join(
            [
                "Provider running:",
                "status: running",
                "type: openai_responses",
                "configured: true",
                "running: true",
                "enabled: true",
                "api_key: set",
                "base_url: https://provider.test",
                "timeout_seconds: 2",
            ]
        )
        assert "status: stopped" in _text(saved_status)
        assert _text(models) == "\n".join(
            [
                "Models for running:",
                "- runtime-model",
            ]
        )
        assert _text(check) == "Provider running reachable. models=1"
        assert _text(started) == "Provider saved started."
        assert store.configs["saved"].enabled is True
        assert _text(reloaded) == "Provider saved reloaded."
        assert _text(stopped) == "Provider running stopped."
        assert store.configs["running"].enabled is False
        assert _text(unknown) == "Unknown provider: missing"

        await runtime.close()

    asyncio.run(run())


def test_builtin_help_command_lists_admin_commands_for_admin() -> None:
    async def run() -> None:
        runtime = await build_cyrene_ai_runtime()
        assert runtime.plugin_manager is not None

        result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/help", name="help"),
                event=_event("/help"),
                is_admin=True,
            )
        )

        assert result.actions[0].message is not None
        text = result.actions[0].message.content[0].text
        assert "Admin:" in text
        assert "/status - Show runtime status. [admin]" in text
        assert "/agent runs [session] [limit] - List agent runs. [admin]" in text
        assert "/agent run <snapshot_id> - Show agent run trace. [admin]" in text
        assert (
            "/agent trace [session] - Show latest agent trace summary. [admin]" in text
        )
        assert "/plugin commands [plugin_id] - List plugin commands. [admin]" in text

        await runtime.close()

    asyncio.run(run())


def test_builtin_help_command_groups_third_party_commands() -> None:
    async def run() -> None:
        runtime = await build_cyrene_ai_runtime()
        assert runtime.plugin_manager is not None
        registry = runtime.plugin_manager._registry
        registry.register(
            PluginDefinition(
                plugin_id="thirdparty.hello",
                name="Hello",
                description="Third-party hello plugin.",
                commands=[
                    PluginCommandDefinition(
                        name="hello",
                        description="Say hello.",
                    )
                ],
            ),
            FakePluginExecutor(),
        )

        result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/help", name="help"),
                event=_event("/help"),
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "\n".join(
            [
                "Available commands:",
                "Built-in:",
                "/start - Start the bot.",
                "/help - Show available commands.",
                "/ping - Check whether the bot is responsive.",
                "/echo <text> - Echo text back.",
                "/session - Show current session.",
                "/session current - Show current session.",
                "/session status <name> - Show session status.",
                "/session ls - List sessions.",
                "/session new <name> - Create and select a session.",
                "/session use <name> - Select a session.",
                "/session rename <old> <new> - Rename a session.",
                "/session clear <name> - Clear session context.",
                "/session delete <name> - Delete a session.",
                "/reset [session] - Reset current session context.",
                "Third-party:",
                "/hello - Say hello. [plugin=thirdparty.hello]",
            ]
        )

        await runtime.close()

    asyncio.run(run())


def test_builtin_plugin_admin_commands_show_command_audit() -> None:
    async def run() -> None:
        runtime = await build_cyrene_ai_runtime()
        assert runtime.plugin_manager is not None
        registry = runtime.plugin_manager._registry
        registry.register(
            PluginDefinition(
                plugin_id="thirdparty.hello",
                name="Hello",
                description="Third-party hello plugin.",
                commands=[
                    PluginCommandDefinition(
                        name="hello",
                        description="Say hello.",
                        aliases=["hi"],
                    )
                ],
            ),
            FakePluginExecutor(),
        )

        list_result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(raw_text="/plugin ls", name="plugin ls"),
                event=_event("/plugin ls"),
                is_admin=True,
            )
        )
        commands_result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/plugin commands thirdparty.hello",
                    name="plugin commands",
                    args=("thirdparty.hello",),
                    args_text="thirdparty.hello",
                ),
                event=_event("/plugin commands thirdparty.hello"),
                is_admin=True,
            )
        )
        status_result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/plugin status thirdparty.hello",
                    name="plugin status",
                    args=("thirdparty.hello",),
                    args_text="thirdparty.hello",
                ),
                event=_event("/plugin status thirdparty.hello"),
                is_admin=True,
            )
        )
        unknown_result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/plugin status missing.plugin",
                    name="plugin status",
                    args=("missing.plugin",),
                    args_text="missing.plugin",
                ),
                event=_event("/plugin status missing.plugin"),
                is_admin=True,
            )
        )

        assert list_result.actions[0].message is not None
        list_text = list_result.actions[0].message.content[0].text
        assert (
            "- thirdparty.hello status=enabled enabled=true kind=third-party commands=1"
            in list_text
        )
        assert commands_result.actions[0].message is not None
        assert commands_result.actions[0].message.content[0].text == "\n".join(
            [
                "Plugin commands:",
                "- /hello plugin=thirdparty.hello kind=third-party status=enabled aliases=/hi admin=false enabled=true: Say hello.",
            ]
        )
        assert status_result.actions[0].message is not None
        assert status_result.actions[0].message.content[0].text == "\n".join(
            [
                "Plugin thirdparty.hello:",
                "status: enabled",
                "enabled: true",
                "kind: third-party",
                "name: Hello",
                "version: 0.1.0",
                "commands:",
                "- /hello aliases=/hi admin=false enabled=true: Say hello.",
            ]
        )
        assert unknown_result.actions[0].message is not None
        assert unknown_result.actions[0].message.content[0].text == (
            "Unknown plugin: missing.plugin"
        )

        await runtime.close()

    asyncio.run(run())


def test_builtin_plugin_commands_render_argument_usage_shapes() -> None:
    async def run() -> None:
        runtime = await build_cyrene_ai_runtime()
        assert runtime.plugin_manager is not None
        registry = runtime.plugin_manager._registry
        registry.register(
            PluginDefinition(
                plugin_id="thirdparty.deploy",
                name="Deploy",
                description="Deploy plugin.",
                commands=[
                    PluginCommandDefinition(
                        name="deploy",
                        description="Deploy an app.",
                        arguments=[
                            PluginCommandArgumentDefinition(
                                name="environment",
                                type="str",
                            ),
                            PluginCommandArgumentDefinition(
                                name="version",
                                type="str",
                                kind=PluginCommandArgumentKind.OPTION,
                                aliases=["-v"],
                            ),
                            PluginCommandArgumentDefinition(
                                name="dry_run",
                                type="bool",
                                kind=PluginCommandArgumentKind.FLAG,
                                aliases=["-n"],
                                required=False,
                            ),
                            PluginCommandArgumentDefinition(
                                name="notes",
                                type="str",
                                kind=PluginCommandArgumentKind.REST,
                                required=False,
                                default="none",
                            ),
                        ],
                    ),
                    PluginCommandDefinition(
                        name="promote",
                        description="Promote an app.",
                        enabled=False,
                    ),
                ],
            ),
            FakePluginExecutor(),
        )

        result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/plugin commands thirdparty.deploy",
                    name="plugin commands",
                    args=("thirdparty.deploy",),
                    args_text="thirdparty.deploy",
                ),
                event=_event("/plugin commands thirdparty.deploy"),
                is_admin=True,
            )
        )
        unknown = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/plugin commands missing.plugin",
                    name="plugin commands",
                    args=("missing.plugin",),
                    args_text="missing.plugin",
                ),
                event=_event("/plugin commands missing.plugin"),
                is_admin=True,
            )
        )

        assert _text(result) == "\n".join(
            [
                "Plugin commands:",
                (
                    "- /deploy <environment> <--version|-v> [--dry-run|-n] "
                    "[notes...=none] plugin=thirdparty.deploy "
                    "kind=third-party status=enabled aliases=- admin=false "
                    "enabled=true: Deploy an app."
                ),
                (
                    "- /promote plugin=thirdparty.deploy kind=third-party "
                    "status=enabled aliases=- admin=false enabled=false: "
                    "Promote an app."
                ),
            ]
        )
        assert _text(unknown) == "Unknown plugin: missing.plugin"

        await runtime.close()

    asyncio.run(run())


def test_builtin_plugin_status_shows_failed_plugin_command_audit() -> None:
    async def run() -> None:
        runtime = await build_cyrene_ai_runtime()
        assert runtime.plugin_manager is not None
        registry = runtime.plugin_manager._registry
        registry.record_status(
            PluginStatusReport(
                plugin_id="thirdparty.failed",
                status=PluginLifecycleStatus.FAILED,
                reason="register_conflict",
                error="该插件命令 hello 已由 thirdparty.hello 注册",
                commands=[
                    PluginCommandDefinition(
                        name="hello",
                        description="Conflicting hello.",
                        aliases=["hi"],
                    )
                ],
            )
        )

        result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/plugin status thirdparty.failed",
                    name="plugin status",
                    args=("thirdparty.failed",),
                    args_text="thirdparty.failed",
                ),
                event=_event("/plugin status thirdparty.failed"),
                is_admin=True,
            )
        )
        commands_result = await runtime.plugin_manager.execute_command(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/plugin commands thirdparty.failed",
                    name="plugin commands",
                    args=("thirdparty.failed",),
                    args_text="thirdparty.failed",
                ),
                event=_event("/plugin commands thirdparty.failed"),
                is_admin=True,
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "\n".join(
            [
                "Plugin thirdparty.failed:",
                "status: failed",
                "enabled: false",
                "kind: failed",
                "reason: register_conflict",
                "error: 该插件命令 hello 已由 thirdparty.hello 注册",
                "commands:",
                "- /hello aliases=/hi admin=false enabled=true: Conflicting hello.",
            ]
        )
        assert commands_result.actions[0].message is not None
        assert commands_result.actions[0].message.content[0].text == "\n".join(
            [
                "Plugin commands:",
                (
                    "- /hello plugin=thirdparty.failed kind=failed "
                    "status=failed reason=register_conflict aliases=/hi "
                    "admin=false enabled=true: Conflicting hello."
                ),
            ]
        )

        await runtime.close()

    asyncio.run(run())
