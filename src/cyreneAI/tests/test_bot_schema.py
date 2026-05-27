from __future__ import annotations

from cyreneAI.core.schema.bot import (
    BotAction,
    BotActionType,
    BotConversationState,
    BotEvent,
    BotEventType,
    BotMessage,
    BotSession,
    BotSessionStatus,
)
from cyreneAI.core.schema.message import ContentPart, ContentPartType


def test_bot_event_schema_carries_channel_message() -> None:
    event = BotEvent(
        event_id="event-1",
        event_type=BotEventType.MESSAGE,
        channel_id="telegram",
        session_id="telegram:user-1",
        user_id="user-1",
        message=BotMessage(
            message_id="message-1",
            sender_id="user-1",
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text="hello",
                )
            ],
        ),
    )

    assert event.event_type == BotEventType.MESSAGE
    assert event.message is not None
    assert event.message.content[0].text == "hello"


def test_bot_action_schema_describes_channel_output() -> None:
    action = BotAction(
        action_type=BotActionType.SEND_MESSAGE,
        channel_id="telegram",
        session_id="telegram:user-1",
        recipient_id="user-1",
        message=BotMessage(
            sender_id="bot",
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text="pong",
                )
            ],
        ),
    )

    assert action.action_type == BotActionType.SEND_MESSAGE
    assert action.message is not None
    assert action.message.sender_id == "bot"


def test_bot_session_schema_keeps_channel_identity() -> None:
    session = BotSession(
        session_id="telegram:user-1",
        channel_id="telegram",
        user_id="user-1",
    )

    assert session.session_id == "telegram:user-1"
    assert session.status == BotSessionStatus.ACTIVE
    assert session.metadata == {}


def test_bot_conversation_state_tracks_session_activity() -> None:
    state = BotConversationState(
        session=BotSession(
            session_id="telegram:user-1",
            channel_id="telegram",
            user_id="user-1",
        ),
        turn_count=2,
        last_event_id="event-2",
    )

    assert state.session.status == BotSessionStatus.ACTIVE
    assert state.turn_count == 2
    assert state.last_event_id == "event-2"
