from __future__ import annotations

import pytest

from cyreneAI.core.errors.bot import BotActionError, BotInputError
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


def test_map_telegram_photo_update_to_image_part() -> None:
    event = map_telegram_update_to_bot_event(
        {
            "update_id": 1003,
            "message": {
                "message_id": 12,
                "from": {"id": 42},
                "chat": {"id": 99, "type": "private"},
                "caption": "look",
                "photo": [
                    {
                        "file_id": "small-file",
                        "file_unique_id": "small-unique",
                        "width": 90,
                        "height": 90,
                    },
                    {
                        "file_id": "large-file",
                        "file_unique_id": "large-unique",
                        "width": 800,
                        "height": 600,
                    },
                ],
            },
        }
    )

    assert event.message is not None
    assert event.message.content[0].text == "look"
    assert event.message.content[1].type == ContentPartType.IMAGE
    assert event.message.content[1].mime_type == "image/jpeg"
    assert event.message.content[1].metadata["telegram_file_id"] == "large-file"


def test_map_telegram_unknown_update_to_bot_event() -> None:
    event = map_telegram_update_to_bot_event({"update_id": 1002})

    assert event.event_type == BotEventType.UNKNOWN
    assert event.session_id == "telegram:unknown:1002"
    assert event.message is None


def test_map_telegram_update_requires_chat_id() -> None:
    with pytest.raises(BotInputError, match="chat.id"):
        map_telegram_update_to_bot_event(
            {
                "update_id": 1004,
                "message": {
                    "message_id": 13,
                    "from": {"id": 42},
                    "chat": {"type": "private"},
                    "text": "hello",
                },
            }
        )


def test_map_telegram_document_image_update_to_image_part() -> None:
    event = map_telegram_update_to_bot_event(
        {
            "update_id": 1005,
            "message": {
                "message_id": 14,
                "chat": {"id": 99, "type": "private"},
                "document": {
                    "file_id": "doc-file",
                    "file_unique_id": "doc-unique",
                    "file_name": "diagram.png",
                    "mime_type": "image/png",
                },
            },
        }
    )

    assert event.user_id is None
    assert event.message is not None
    assert event.message.content[0].text == ""
    assert event.message.content[1].type == ContentPartType.IMAGE
    assert event.message.content[1].mime_type == "image/png"
    assert event.message.content[1].metadata == {
        "telegram_file_id": "doc-file",
        "telegram_file_unique_id": "doc-unique",
        "telegram_file_name": "diagram.png",
    }


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


def test_map_send_message_action_uses_metadata_and_thread_id() -> None:
    payload = map_bot_action_to_send_message_payload(
        BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id="telegram",
            session_id="telegram:99",
            thread_id="topic-7",
            metadata={"telegram_chat_id": "99"},
            message=BotMessage(
                content=[
                    ContentPart(type=ContentPartType.TEXT, text="first"),
                    ContentPart(type=ContentPartType.IMAGE, mime_type="image/png"),
                    ContentPart(type=ContentPartType.TEXT, text="second"),
                ]
            ),
        )
    )

    assert payload == {
        "chat_id": "99",
        "message_thread_id": "topic-7",
        "text": "first\nsecond",
    }


def test_map_send_message_action_falls_back_to_recipient_and_session_chat_id() -> None:
    recipient_payload = map_bot_action_to_send_message_payload(
        BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id="telegram",
            session_id="other-session",
            recipient_id="recipient-42",
            message=BotMessage(
                content=[ContentPart(type=ContentPartType.TEXT, text="hello")]
            ),
        )
    )
    session_payload = map_bot_action_to_send_message_payload(
        BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id="telegram",
            session_id="telegram:12345",
            message=BotMessage(
                content=[ContentPart(type=ContentPartType.TEXT, text="hello")]
            ),
        )
    )

    assert recipient_payload["chat_id"] == "recipient-42"
    assert session_payload["chat_id"] == "12345"


def test_map_send_message_action_rejects_unsupported_action_and_missing_chat_id() -> None:
    with pytest.raises(BotActionError, match="does not support"):
        map_bot_action_to_send_message_payload(
            BotAction.model_construct(
                action_type="delete_message",
                channel_id="telegram",
                session_id="telegram:99",
            )
        )

    with pytest.raises(BotActionError, match="chat id"):
        map_bot_action_to_send_message_payload(
            BotAction(
                action_type=BotActionType.SEND_MESSAGE,
                channel_id="telegram",
                session_id="memory:99",
                message=BotMessage(
                    content=[ContentPart(type=ContentPartType.TEXT, text="hello")]
                ),
            )
        )


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
