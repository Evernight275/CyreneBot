from __future__ import annotations

import asyncio

import pytest

from cyreneAI.core.errors.plugin import PluginConfigurationError, PluginExecutionError
from cyreneAI.core.schema.bot import BotCommand, BotEvent, BotEventType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.plugin import PluginCommandRequest, PluginManifest
from cyreneAI.plugin_api import CyreneBot, text


def _event(text_value: str = "/hello") -> BotEvent:
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
                    text=text_value,
                )
            ]
        ),
    )


def test_cyrene_bot_requires_manifest_before_loader_configures_it() -> None:
    plugin = CyreneBot()

    with pytest.raises(PluginConfigurationError):
        _ = plugin.manifest

    manifest = PluginManifest(
        plugin_id="demo.hello",
        name="Hello",
        description="Hello plugin.",
        entrypoint="main.py",
    )
    plugin.configure(manifest)

    assert plugin.manifest is manifest


def test_cyrene_bot_command_decorator_records_local_route() -> None:
    plugin = CyreneBot()

    @plugin.command("/hello", aliases=["hi"], admin_required=True)
    async def hello(request, ctx):
        """Say hello."""
        return text(request, "hello")

    routes = plugin.routes

    assert len(routes) == 1
    assert routes[0].name == "hello"
    assert routes[0].description == "Say hello."
    assert routes[0].usage == "/hello"
    assert routes[0].aliases == ["hi"]
    assert routes[0].admin_required is True


def test_text_helper_builds_standard_bot_action() -> None:
    result = text(
        PluginCommandRequest(
            command=BotCommand(raw_text="/hello", name="hello"),
            event=_event(),
        ),
        "Hello!",
    )

    assert len(result.actions) == 1
    action = result.actions[0]
    assert action.channel_id == "memory"
    assert action.session_id == "memory:user-1"
    assert action.recipient_id == "user-1"
    assert action.message is not None
    assert action.message.content[0].text == "Hello!"


def test_cyrene_bot_command_executor_requires_standard_result() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.bad",
                name="Bad",
                description="Bad plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/bad")
        async def bad(request, ctx):
            return "bad"

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self, definition):
                raise AssertionError

        context = Context()
        plugin.setup(context)

        with pytest.raises(PluginExecutionError):
            await context.executor.execute(
                PluginCommandRequest(
                    command=BotCommand(raw_text="/bad", name="bad"),
                    event=_event("/bad"),
                )
            )

    asyncio.run(run())
