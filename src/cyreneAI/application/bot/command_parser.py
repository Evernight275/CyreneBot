from __future__ import annotations

import shlex

from cyreneAI.core.errors.bot import BotInputError
from cyreneAI.core.schema.bot import BotEvent, BotEventType, BotCommand
from cyreneAI.core.schema.message import ContentPartType


def parse_bot_command(event: BotEvent) -> BotCommand:
    """
    从标准 BotEvent 中解析 /command 参数。
    """
    raw_text = _event_text(event).strip()
    if not raw_text.startswith("/"):
        raise BotInputError("COMMAND event text must start with /")

    command_text = raw_text[1:].strip()
    if not command_text:
        raise BotInputError("COMMAND event must include command name")

    try:
        parts = shlex.split(command_text)
    except ValueError as exc:
        raise BotInputError(f"Invalid command syntax: {exc}") from exc
    if not parts:
        raise BotInputError("COMMAND event must include command name")

    name_token, *args = parts
    name, target = _split_command_target(name_token)
    if not name:
        raise BotInputError("COMMAND event must include command name")

    return BotCommand(
        raw_text=raw_text,
        name=name.lower(),
        target=target,
        args=tuple(args),
        args_text=" ".join(args),
    )


def should_parse_bot_command(event: BotEvent) -> bool:
    """
    判断标准事件是否应该直接按 bot 命令处理。
    """
    if event.event_type == BotEventType.COMMAND:
        return True
    if event.event_type != BotEventType.MESSAGE:
        return False
    try:
        return _event_text(event).strip().startswith("/")
    except BotInputError:
        return False


def render_bot_command_result(command: BotCommand) -> str:
    """
    渲染内置命令结果，供 channel 直接回复。
    """
    if command.name == "start":
        return "\n".join(
            [
                "CyreneAI bot is ready.",
                "Use /help to see available commands.",
            ]
        )
    if command.name == "help":
        return "\n".join(
            [
                "Available commands:",
                "/start - Start the bot.",
                "/help - Show available commands.",
                "/ping - Check whether the bot is responsive.",
                "/echo <text> - Echo text back.",
            ]
        )
    if command.name == "ping":
        return "pong"
    if command.name == "echo":
        return command.args_text or "(empty)"
    return "\n".join(
        [
            f"Unknown command: {command.name}",
            "Use /help to see available commands.",
        ]
    )


def _split_command_target(name_token: str) -> tuple[str, str | None]:
    name, separator, target = name_token.partition("@")
    if not separator:
        return name, None
    return name, target or None


def _event_text(event: BotEvent) -> str:
    if event.message is None:
        raise BotInputError("COMMAND event must include message")

    chunks = [
        part.text
        for part in event.message.content
        if part.type == ContentPartType.TEXT and part.text
    ]
    if not chunks:
        raise BotInputError("COMMAND event must include text content")
    return "\n".join(chunks)
