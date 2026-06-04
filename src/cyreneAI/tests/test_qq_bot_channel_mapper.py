from __future__ import annotations

import pytest

from cyreneAI.core.errors.bot import BotActionError
from cyreneAI.core.schema.bot import BotAction, BotActionType, BotEventType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.infra.adapters.channels.qq.mapper import (
    map_bot_action_to_qq_send_message_payload,
    map_qq_update_to_bot_event,
)


def test_map_qq_channel_message_update_to_bot_event() -> None:
    event = map_qq_update_to_bot_event(
        {
            "id": "event-1",
            "t": "AT_MESSAGE_CREATE",
            "s": 10,
            "d": {
                "id": "message-1",
                "channel_id": "channel-1",
                "guild_id": "guild-1",
                "author": {"id": "user-1"},
                "content": "hello",
            },
        }
    )

    assert event.event_id == "event-1"
    assert event.event_type == BotEventType.MESSAGE
    assert event.channel_id == "qq"
    assert event.session_id == "qq:channel:channel-1"
    assert event.user_id == "user-1"
    assert event.thread_id == "channel-1"
    assert event.message is not None
    assert event.message.message_id == "message-1"
    assert event.message.sender_id == "user-1"
    assert event.message.content[0].text == "hello"
    assert event.metadata["qq_channel_id"] == "channel-1"
    assert event.metadata["qq_guild_id"] == "guild-1"
    assert event.metadata["qq_sequence"] == 10


def test_map_qq_group_command_update_to_bot_event() -> None:
    event = map_qq_update_to_bot_event(
        {
            "t": "GROUP_AT_MESSAGE_CREATE",
            "d": {
                "id": "message-2",
                "group_openid": "group-1",
                "user_openid": "user-2",
                "content": "/help",
            },
        }
    )

    assert event.event_type == BotEventType.COMMAND
    assert event.session_id == "qq:group:group-1"
    assert event.user_id == "user-2"
    assert event.metadata["qq_group_openid"] == "group-1"
    assert event.metadata["qq_user_openid"] == "user-2"


def test_map_qq_unknown_update_to_bot_event() -> None:
    event = map_qq_update_to_bot_event({"id": "event-3", "t": "READY", "d": {}})

    assert event.event_type == BotEventType.UNKNOWN
    assert event.session_id == "qq:unknown:event-3"
    assert event.message is None


def test_map_send_message_action_to_qq_channel_payload() -> None:
    payload = map_bot_action_to_qq_send_message_payload(
        BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id="qq",
            session_id="qq:channel:channel-1",
            thread_id="channel-1",
            message=BotMessage(
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text="pong",
                    )
                ]
            ),
            metadata={"qq_message_id": "message-1"},
        )
    )

    assert payload == {
        "content": "pong",
        "_route": "channel",
        "_route_id": "channel-1",
        "msg_id": "message-1",
    }


def test_map_send_message_action_to_qq_group_payload_from_session() -> None:
    payload = map_bot_action_to_qq_send_message_payload(
        BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id="qq",
            session_id="qq:group:group-1",
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
        "content": "pong",
        "_route": "group",
        "_route_id": "group-1",
    }


def test_map_send_message_action_rejects_missing_text() -> None:
    with pytest.raises(BotActionError):
        map_bot_action_to_qq_send_message_payload(
            BotAction(
                action_type=BotActionType.SEND_MESSAGE,
                channel_id="qq",
                session_id="qq:channel:channel-1",
            )
        )
