from __future__ import annotations

import asyncio
from pathlib import Path

from cyreneAI.bootstrap import build_cyrene_ai_runtime
from cyreneAI.core.schema.bot import BotCommand, BotEvent, BotEventType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.plugin import PluginCommandRequest
from cyreneAI.infra.adapters.plugins.filesystem import FileSystemPluginLoader


PROJECT_ROOT = Path(__file__).parents[3]
DEMO_PLUGIN_PATH = PROJECT_ROOT / "examples" / "plugins" / "demo_hello"


def _event() -> BotEvent:
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
                    text="/hello developer",
                )
            ]
        ),
    )


def test_demo_plugin_project_loads_and_handles_command() -> None:
    async def run() -> None:
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[FileSystemPluginLoader(DEMO_PLUGIN_PATH)],
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_manager is not None
            assert [plugin.plugin_id for plugin in runtime.plugin_manager.list_plugins()] == [
                "demo.hello"
            ]
            assert [command.name for command in runtime.plugin_manager.list_commands()] == [
                "hello"
            ]

            result = await runtime.plugin_manager.execute_command(
                PluginCommandRequest(
                    command=BotCommand(
                        raw_text="/hello developer",
                        name="hello",
                        args=("developer",),
                        args_text="developer",
                    ),
                    event=_event(),
                )
            )

            assert result.actions[0].message is not None
            assert result.actions[0].message.content[0].text == "Hello, developer!"
        finally:
            await runtime.close()

    asyncio.run(run())
