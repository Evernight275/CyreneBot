from __future__ import annotations

import asyncio

from cyreneAI.core.schema.bot import (
    BotAction,
    BotActionType,
    BotEvent,
    BotEventType,
    BotMessage,
)
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.infra.adapters.channels.memory import InMemoryBotChannel


def _message(text: str) -> BotMessage:
    return BotMessage(
        content=[
            ContentPart(
                type=ContentPartType.TEXT,
                text=text,
            )
        ]
    )


def test_in_memory_bot_channel_records_events_and_actions() -> None:
    async def run() -> None:
        channel = InMemoryBotChannel()
        event = BotEvent(
            event_id="event-1",
            event_type=BotEventType.MESSAGE,
            channel_id="memory",
            session_id="memory:user-1",
            message=_message("hello"),
        )
        action = BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id="memory",
            session_id="memory:user-1",
            message=_message("pong"),
        )

        channel.push_event(event)
        assert channel.pop_event() == event
        assert channel.pop_event() is None

        await channel.send(action)
        assert channel.list_actions() == [action]

        channel.clear()
        assert channel.events == []
        assert channel.actions == []

    asyncio.run(run())
