from __future__ import annotations

import shlex

from cyreneAI.core.errors.bot import BotInputError
from cyreneAI.core.schema.bot import BotCommand, BotEvent, BotEventType
from cyreneAI.core.schema.message import ContentPartType


def parse_bot_command(
    event: BotEvent,
    *,
    known_command_names: set[str] | None = None,
) -> BotCommand:
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

    name_token, args = _split_command_parts(parts, known_command_names)
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


def _split_command_target(name_token: str) -> tuple[str, str | None]:
    name, separator, target = name_token.partition("@")
    if not separator:
        return name, None
    return name, target or None


def _split_command_parts(
    parts: list[str],
    known_command_names: set[str] | None,
) -> tuple[str, list[str]]:
    if not known_command_names:
        name_token, *args = parts
        return name_token, args

    first_name, target = _split_command_target(parts[0])
    normalized_names = {_normalize_command_name(name) for name in known_command_names}
    best_size = 0
    best_name = ""
    for size in range(1, len(parts) + 1):
        candidate_parts = [first_name, *parts[1:size]]
        candidate = _normalize_command_name(" ".join(candidate_parts))
        if candidate in normalized_names:
            best_size = size
            best_name = candidate

    if best_size == 0:
        name_token, *args = parts
        return name_token, args

    if target is not None:
        best_name = f"{best_name}@{target}"
    return best_name, parts[best_size:]


def _normalize_command_name(value: str) -> str:
    return " ".join(value.strip().removeprefix("/").split()).lower()


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
