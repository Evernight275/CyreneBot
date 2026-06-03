from __future__ import annotations

import asyncio

from cyreneAI.application.bootstrap import build_cyrene_ai_runtime
from cyreneAI.application.plugins.builtin_bot_commands import (
    BUILTIN_BOT_COMMANDS_PLUGIN_ID,
)
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.context.manager import ContextManager
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
    PluginCommandRequest,
    PluginCommandResult,
    PluginDefinition,
    PluginLifecycleStatus,
    PluginStatusReport,
)
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
        ) in (
            listed.actions[0].message.content[0].text
        )

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
                "completed: true",
                "stop_reason: final_response",
                "steps: 2",
                "tool_calls: 1",
                "tool_results: 1",
                "tool_errors: 0",
                "tools: lookup",
                "trace_items: 2",
                "last_assistant: final answer",
            ]
        )

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
        assert "/agent trace [session] - Show latest agent trace summary. [admin]" in text
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
        assert "- thirdparty.hello status=enabled enabled=true kind=third-party commands=1" in list_text
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
