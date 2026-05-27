from __future__ import annotations

import asyncio

import pytest

from cyreneAI.core.errors.bot import BotConfigurationError
from cyreneAI.core.schema.bot import BotAction, BotActionType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.infra.adapters.channels.telegram import TelegramBotChannel


class FakeTelegramClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self.closed = False

    async def send_message(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {"message_id": 1}

    async def close(self) -> None:
        self.closed = True


def _action(text: str = "pong") -> BotAction:
    return BotAction(
        action_type=BotActionType.SEND_MESSAGE,
        channel_id="telegram",
        session_id="telegram:99",
        thread_id="99",
        message=BotMessage(
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=text,
                )
            ]
        ),
    )


def test_telegram_bot_channel_requires_token_without_client() -> None:
    with pytest.raises(BotConfigurationError):
        TelegramBotChannel()


def test_telegram_bot_channel_sends_message_action() -> None:
    async def run() -> None:
        client = FakeTelegramClient()
        channel = TelegramBotChannel(bot_client=client)

        await channel.send(_action())

        assert client.payloads == [
            {
                "chat_id": "99",
                "text": "pong",
            }
        ]
        await channel.close()
        assert client.closed is True

    asyncio.run(run())


def test_telegram_bot_channel_maps_update() -> None:
    channel = TelegramBotChannel(bot_client=FakeTelegramClient())

    event = channel.map_update(
        {
            "update_id": 1000,
            "message": {
                "message_id": 10,
                "from": {"id": 42},
                "chat": {"id": 99, "type": "private"},
                "text": "hello",
            },
        }
    )

    assert event.session_id == "telegram:99"
    assert event.message is not None
    assert event.message.content[0].text == "hello"
