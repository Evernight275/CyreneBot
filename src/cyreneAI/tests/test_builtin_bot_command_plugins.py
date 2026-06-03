from __future__ import annotations

import asyncio

from cyreneAI.application.bootstrap import build_cyrene_ai_runtime
from cyreneAI.application.plugins.builtin_bot_commands import (
    BUILTIN_BOT_COMMANDS_PLUGIN_ID,
)
from cyreneAI.core.schema.bot import BotCommand, BotEvent, BotEventType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.plugin import PluginCommandRequest


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
        assert "/status - Show runtime status. [admin]" in text

        await runtime.close()

    asyncio.run(run())
