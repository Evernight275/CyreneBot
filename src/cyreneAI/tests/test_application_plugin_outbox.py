from __future__ import annotations

import asyncio

from cyreneAI.application.plugins.outbox import ApplicationPluginOutbox
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.errors.bot import BotActionError
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.bot import (
    BotChannelDefinition,
    BotEvent,
    BotEventType,
)
from cyreneAI.infra.adapters.bot_sessions.memory import InMemoryBotSessionStore
from cyreneAI.infra.adapters.channels.memory import InMemoryBotChannel


class FailingChannel:
    def __init__(self) -> None:
        self.actions = []

    async def send(self, action) -> None:
        self.actions.append(action)
        raise BotActionError("send failed")


def test_plugin_outbox_enforces_min_interval() -> None:
    async def run() -> None:
        channel = InMemoryBotChannel()
        runtime, clock = await _runtime(channel, "memory:user-1")
        outbox = ApplicationPluginOutbox(
            runtime,
            min_interval_seconds=10,
            max_per_session_per_hour=10,
            max_per_plugin_per_hour=10,
            clock=lambda: clock["now"],
        )
        messages = outbox.namespace("demo.plugin")

        first = await messages.send("memory:user-1", text="one")
        second = await messages.send("memory:user-1", text="two")
        clock["now"] += 10
        third = await messages.send("memory:user-1", text="three")

        assert first.accepted is True
        assert second.accepted is False
        assert second.metadata["reason"] == "min_interval"
        assert third.accepted is True
        assert [action.message.content[0].text for action in channel.actions] == [
            "one",
            "three",
        ]

    asyncio.run(run())


def test_plugin_outbox_enforces_session_hourly_limit() -> None:
    async def run() -> None:
        channel = InMemoryBotChannel()
        runtime, clock = await _runtime(channel, "memory:user-1")
        outbox = ApplicationPluginOutbox(
            runtime,
            min_interval_seconds=0,
            max_per_session_per_hour=2,
            max_per_plugin_per_hour=10,
            clock=lambda: clock["now"],
        )
        messages = outbox.namespace("demo.plugin")

        assert (await messages.send("memory:user-1", text="one")).accepted is True
        assert (await messages.send("memory:user-1", text="two")).accepted is True
        limited = await messages.send("memory:user-1", text="three")

        assert limited.accepted is False
        assert limited.metadata["reason"] == "session_hourly_limit"
        assert len(channel.actions) == 2

    asyncio.run(run())


def test_plugin_outbox_enforces_plugin_hourly_limit() -> None:
    async def run() -> None:
        channel = InMemoryBotChannel()
        runtime, clock = await _runtime(
            channel,
            "memory:user-1",
            "memory:user-2",
            "memory:user-3",
        )
        outbox = ApplicationPluginOutbox(
            runtime,
            min_interval_seconds=0,
            max_per_session_per_hour=10,
            max_per_plugin_per_hour=2,
            clock=lambda: clock["now"],
        )
        messages = outbox.namespace("demo.plugin")

        assert (await messages.send("memory:user-1", text="one")).accepted is True
        assert (await messages.send("memory:user-2", text="two")).accepted is True
        limited = await messages.send("memory:user-3", text="three")

        assert limited.accepted is False
        assert limited.metadata["reason"] == "plugin_hourly_limit"
        assert len(channel.actions) == 2

    asyncio.run(run())


def test_plugin_outbox_requires_namespace_permission_for_bypass() -> None:
    async def run() -> None:
        channel = InMemoryBotChannel()
        runtime, clock = await _runtime(channel, "memory:user-1")
        outbox = ApplicationPluginOutbox(
            runtime,
            min_interval_seconds=10,
            max_per_session_per_hour=10,
            max_per_plugin_per_hour=10,
            clock=lambda: clock["now"],
        )
        messages = outbox.namespace("demo.plugin")

        first = await messages.send(
            "memory:user-1",
            text="one",
            bypass_rate_limit=True,
        )
        second = await messages.send(
            "memory:user-1",
            text="two",
            bypass_rate_limit=True,
        )

        assert first.accepted is True
        assert "rate_limit_bypassed" not in first.metadata
        assert second.accepted is False
        assert second.metadata["reason"] == "min_interval"
        assert [action.message.content[0].text for action in channel.actions] == ["one"]

    asyncio.run(run())


def test_plugin_outbox_allows_explicit_bypass_when_namespace_has_permission() -> None:
    async def run() -> None:
        channel = InMemoryBotChannel()
        runtime, clock = await _runtime(channel, "memory:user-1")
        outbox = ApplicationPluginOutbox(
            runtime,
            min_interval_seconds=10,
            max_per_session_per_hour=1,
            max_per_plugin_per_hour=1,
            clock=lambda: clock["now"],
        )
        messages = outbox.namespace(
            "demo.plugin",
            can_bypass_rate_limit=True,
        )

        first = await messages.send(
            "memory:user-1",
            text="one",
            bypass_rate_limit=True,
        )
        second = await messages.send(
            "memory:user-1",
            text="two",
            bypass_rate_limit=True,
        )

        assert first.accepted is True
        assert first.metadata["rate_limit_bypassed"] is True
        assert second.accepted is True
        assert second.metadata["rate_limit_bypassed"] is True
        assert [action.message.content[0].text for action in channel.actions] == [
            "one",
            "two",
        ]
        assert channel.actions[1].metadata["rate_limit_bypassed"] is True

    asyncio.run(run())


def test_plugin_outbox_returns_rejected_receipt_when_channel_send_fails() -> None:
    async def run() -> None:
        channel = FailingChannel()
        runtime, clock = await _runtime(channel, "memory:user-1")
        outbox = ApplicationPluginOutbox(
            runtime,
            min_interval_seconds=10,
            max_per_session_per_hour=10,
            max_per_plugin_per_hour=10,
            clock=lambda: clock["now"],
        )
        messages = outbox.namespace("demo.plugin")

        receipt = await messages.send("memory:user-1", text="one")

        assert receipt.accepted is False
        assert receipt.metadata["send_failed"] is True
        assert receipt.metadata["reason"] == "send failed"
        assert receipt.metadata["plugin_id"] == "demo.plugin"
        assert len(channel.actions) == 1

    asyncio.run(run())


async def _runtime(
    channel,
    *session_ids: str,
) -> tuple[CyreneAIRuntime, dict[str, float]]:
    channel_registry = BotChannelRegistry()
    channel_registry.register(
        BotChannelDefinition(
            channel_id="memory",
            name="Memory",
        ),
        channel,
    )
    session_manager = BotSessionManager(InMemoryBotSessionStore())
    for index, session_id in enumerate(session_ids, start=1):
        await session_manager.get_or_create(
            BotEvent(
                event_id=f"event-{index}",
                event_type=BotEventType.MESSAGE,
                channel_id="memory",
                session_id=session_id,
                user_id=f"user-{index}",
            )
        )

    runtime = CyreneAIRuntime(
        provider_manager=ProviderManager(ProviderFactory()),
        context_builder=ContextWindowBuilder(),
        bot_channel_registry=channel_registry,
        bot_session_manager=session_manager,
    )
    return runtime, {"now": 100.0}
