from __future__ import annotations

import asyncio

from cyreneAI.application.bootstrap import build_cyrene_ai_runtime
from cyreneAI.application.plugins.builtin_bot_commands import (
    BUILTIN_BOT_COMMANDS_PLUGIN_ID,
)
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.schema.bot import BotCommand, BotEvent, BotEventType, BotMessage
from cyreneAI.core.schema.context import ContextSnapshot, ContextWindow
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.plugin import PluginCommandRequest
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
            "session ls",
            "session new",
            "session use",
            "session rename",
            "session delete",
            "reset",
            "status",
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
                "/start - Start the bot.",
                "/help - Show available commands.",
                "/ping - Check whether the bot is responsive.",
                "/echo <text> - Echo text back.",
                "/session - Show current session.",
                "/session current - Show current session.",
                "/session ls - List sessions.",
                "/session new <name> - Create and select a session.",
                "/session use <name> - Select a session.",
                "/session rename <old> <new> - Rename a session.",
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
                "Current session:",
                "name: default",
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
                "- default",
                "* work",
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
        assert "/status - Show runtime status. [admin]" in text

        await runtime.close()

    asyncio.run(run())
