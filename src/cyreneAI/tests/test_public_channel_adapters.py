from __future__ import annotations

import asyncio

from cyreneAI.adapters.channels import (
    InMemoryBotChannel,
    TelegramBotChannel,
    create_memory_bot_channel,
    create_telegram_bot_channel,
)
from cyreneAI.core.schema.bot import BotAction, BotActionType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType


def test_create_memory_bot_channel_returns_in_memory_channel() -> None:
    channel = create_memory_bot_channel()

    assert isinstance(channel, InMemoryBotChannel)


def test_create_memory_bot_channel_returns_independent_instances() -> None:
    async def run() -> None:
        first = create_memory_bot_channel()
        second = create_memory_bot_channel()
        action = BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id="memory",
            session_id="memory:user-1",
            message=BotMessage(
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text="pong",
                    )
                ]
            ),
        )

        await first.send(action)

        assert first is not second
        assert first.list_actions() == [action]
        assert second.list_actions() == []

    asyncio.run(run())


def test_create_telegram_bot_channel_returns_telegram_channel() -> None:
    channel = create_telegram_bot_channel(
        token="token",
        base_url="https://telegram.example",
    )

    assert isinstance(channel, TelegramBotChannel)
