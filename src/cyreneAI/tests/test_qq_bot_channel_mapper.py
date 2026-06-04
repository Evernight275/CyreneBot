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


def test_map_qq_group_update_prefers_group_route_over_channel_id() -> None:
    event = map_qq_update_to_bot_event(
        {
            "t": "GROUP_AT_MESSAGE_CREATE",
            "d": {
                "id": "message-2",
                "channel_id": "not-a-real-channel",
                "group_openid": "group-1",
                "user_openid": "user-2",
                "content": "hello",
            },
        }
    )

    assert event.session_id == "qq:group:group-1"
    assert event.thread_id == "group-1"
    assert event.metadata["qq_channel_id"] == "not-a-real-channel"
    assert event.metadata["qq_group_openid"] == "group-1"


def test_map_qq_direct_message_update_to_dm_event() -> None:
    event = map_qq_update_to_bot_event(
        {
            "t": "DIRECT_MESSAGE_CREATE",
            "d": {
                "id": "message-3",
                "channel_id": "dm-channel-1",
                "guild_id": "guild-1",
                "author": {"id": "user-3"},
                "content": "hello",
            },
        }
    )

    assert event.event_type == BotEventType.MESSAGE
    assert event.session_id == "qq:dm:guild-1"
    assert event.user_id == "user-3"
    assert event.thread_id == "guild-1"
    assert event.metadata["qq_channel_id"] == "dm-channel-1"
    assert event.metadata["qq_guild_id"] == "guild-1"


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
        "msg_type": 0,
    }


def test_map_send_message_action_prefers_group_metadata_for_group_event() -> None:
    payload = map_bot_action_to_qq_send_message_payload(
        BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id="qq",
            session_id="qq:group:group-1",
            thread_id="group-1",
            message=BotMessage(
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text="pong",
                    )
                ]
            ),
            metadata={
                "qq_event_type": "GROUP_AT_MESSAGE_CREATE",
                "qq_channel_id": "not-a-real-channel",
                "qq_group_openid": "group-1",
                "qq_message_id": "message-1",
            },
        )
    )

    assert payload == {
        "content": "pong",
        "_route": "group",
        "_route_id": "group-1",
        "msg_type": 0,
        "msg_id": "message-1",
        "msg_seq": 1,
    }


def test_map_send_message_action_prefers_user_metadata_for_c2c_event() -> None:
    payload = map_bot_action_to_qq_send_message_payload(
        BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id="qq",
            session_id="qq:user:user-1",
            thread_id="user-1",
            message=BotMessage(
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text="pong",
                    )
                ]
            ),
            metadata={
                "qq_event_type": "C2C_MESSAGE_CREATE",
                "qq_user_openid": "user-1",
                "qq_message_id": "message-1",
            },
        )
    )

    assert payload == {
        "content": "pong",
        "_route": "user",
        "_route_id": "user-1",
        "msg_type": 0,
        "msg_id": "message-1",
        "msg_seq": 1,
    }


def test_map_send_message_action_uses_session_route_before_raw_thread_id() -> None:
    payload = map_bot_action_to_qq_send_message_payload(
        BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id="qq",
            session_id="qq:user:user-1",
            thread_id="user-1",
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
        "_route": "user",
        "_route_id": "user-1",
        "msg_type": 0,
    }


def test_map_send_message_action_uses_session_route_before_typed_thread_id() -> None:
    payload = map_bot_action_to_qq_send_message_payload(
        BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id="qq",
            session_id="qq:user:user-1",
            thread_id="qq:channel:not-a-real-channel",
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
        "_route": "user",
        "_route_id": "user-1",
        "msg_type": 0,
    }


def test_map_send_message_action_prefers_dm_metadata_for_direct_message_event() -> None:
    payload = map_bot_action_to_qq_send_message_payload(
        BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id="qq",
            session_id="qq:dm:guild-1",
            thread_id="guild-1",
            message=BotMessage(
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text="pong",
                    )
                ]
            ),
            metadata={
                "qq_event_type": "DIRECT_MESSAGE_CREATE",
                "qq_channel_id": "dm-channel-1",
                "qq_guild_id": "guild-1",
                "qq_user_id": "user-1",
                "qq_message_id": "message-1",
            },
        )
    )

    assert payload == {
        "content": "pong",
        "_route": "dm",
        "_route_id": "guild-1",
        "msg_id": "message-1",
    }


def test_map_send_message_action_uses_dm_session_route_before_raw_thread_id() -> None:
    payload = map_bot_action_to_qq_send_message_payload(
        BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id="qq",
            session_id="qq:dm:guild-1",
            thread_id="guild-1",
            message=BotMessage(
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text="pong",
                    )
                ]
            ),
            metadata={
                "qq_message_id": "message-1",
            },
        )
    )

    assert payload == {
        "content": "pong",
        "_route": "dm",
        "_route_id": "guild-1",
        "msg_id": "message-1",
    }


def test_map_send_message_action_uses_qq_msg_seq_metadata() -> None:
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
            metadata={
                "qq_message_id": "message-1",
                "qq_msg_seq": "7",
            },
        )
    )

    assert payload == {
        "content": "pong",
        "_route": "group",
        "_route_id": "group-1",
        "msg_type": 0,
        "msg_id": "message-1",
        "msg_seq": 7,
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
