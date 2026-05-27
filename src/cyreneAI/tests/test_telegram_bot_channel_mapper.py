from __future__ import annotations

import pytest

from cyreneAI.core.errors.bot import BotActionError
from cyreneAI.core.schema.bot import BotAction, BotActionType, BotEventType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.infra.adapters.channels.telegram.mapper import (
    map_bot_action_to_send_message_payload,
    map_telegram_update_to_bot_event,
)


def test_map_telegram_message_update_to_bot_event() -> None:
    event = map_telegram_update_to_bot_event(
        {
            "update_id": 1000,
            "message": {
                "message_id": 10,
                "from": {"id": 42, "is_bot": False, "first_name": "Ada"},
                "chat": {"id": 99, "type": "private"},
                "text": "hello",
            },
        }
    )

    assert event.event_id == "1000"
    assert event.event_type == BotEventType.MESSAGE
    assert event.channel_id == "telegram"
    assert event.session_id == "telegram:99"
    assert event.user_id == "42"
    assert event.thread_id == "99"
    assert event.message is not None
    assert event.message.message_id == "10"
    assert event.message.sender_id == "42"
    assert event.message.content[0].text == "hello"
    assert event.metadata["telegram_chat_id"] == "99"


def test_map_telegram_command_update_to_bot_event() -> None:
    event = map_telegram_update_to_bot_event(
        {
            "update_id": 1001,
            "message": {
                "message_id": 11,
                "from": {"id": 42},
                "chat": {"id": 99, "type": "private"},
                "text": "/start",
            },
        }
    )

    assert event.event_type == BotEventType.COMMAND


def test_map_telegram_unknown_update_to_bot_event() -> None:
    event = map_telegram_update_to_bot_event({"update_id": 1002})

    assert event.event_type == BotEventType.UNKNOWN
    assert event.session_id == "telegram:unknown:1002"
    assert event.message is None


def test_map_send_message_action_to_telegram_payload() -> None:
    payload = map_bot_action_to_send_message_payload(
        BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id="telegram",
            session_id="telegram:99",
            thread_id="99",
            message=BotMessage(
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text="pong",
                    )
                ]
            ),
        )
    )

    assert payload == {
        "chat_id": "99",
        "text": "pong",
    }


def test_map_send_message_action_rejects_missing_text() -> None:
    with pytest.raises(BotActionError):
        map_bot_action_to_send_message_payload(
            BotAction(
                action_type=BotActionType.SEND_MESSAGE,
                channel_id="telegram",
                session_id="telegram:99",
                thread_id="99",
            )
        )
