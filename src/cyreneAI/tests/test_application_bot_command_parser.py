from __future__ import annotations

import pytest

from cyreneAI.application.bot.command_parser import (
    parse_bot_command,
    should_parse_bot_command,
)
from cyreneAI.core.errors.bot import BotInputError
from cyreneAI.core.schema.bot import BotEvent, BotEventType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType


def _command_event(text: str) -> BotEvent:
    return BotEvent(
        event_id="event-1",
        event_type=BotEventType.COMMAND,
        channel_id="test-channel",
        session_id="test-channel:user-1",
        user_id="user-1",
        message=BotMessage(
            sender_id="user-1",
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=text,
                )
            ],
        ),
    )


def test_parse_bot_command_splits_name_and_arguments() -> None:
    command = parse_bot_command(_command_event('/search "hello world" --limit 3'))

    assert command.raw_text == '/search "hello world" --limit 3'
    assert command.name == "search"
    assert command.target is None
    assert command.args == ("hello world", "--limit", "3")
    assert command.args_text == "hello world --limit 3"


def test_parse_bot_command_supports_target_suffix() -> None:
    command = parse_bot_command(_command_event("/Start@CyreneBot now"))

    assert command.name == "start"
    assert command.target == "CyreneBot"
    assert command.args == ("now",)


def test_parse_bot_command_rejects_non_command_text() -> None:
    with pytest.raises(BotInputError):
        parse_bot_command(_command_event("hello"))


def test_should_parse_bot_command_accepts_slash_message() -> None:
    event = _command_event("/help")
    event = event.model_copy(update={"event_type": BotEventType.MESSAGE})

    assert should_parse_bot_command(event) is True


def test_should_parse_bot_command_rejects_regular_message() -> None:
    event = _command_event("hello")
    event = event.model_copy(update={"event_type": BotEventType.MESSAGE})

    assert should_parse_bot_command(event) is False
