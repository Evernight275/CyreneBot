from __future__ import annotations

from dataclasses import dataclass, field
import shlex

from cyreneAI.core.errors.bot import BotInputError
from cyreneAI.core.schema.bot import BotEvent, BotEventType
from cyreneAI.core.schema.message import ContentPartType


@dataclass(frozen=True)
class BotCommand:
    """
    标准 bot 命令解析结果。
    """

    raw_text: str
    name: str
    args: list[str] = field(default_factory=list)
    args_text: str = ""


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

    name, *args = parts
    return BotCommand(
        raw_text=raw_text,
        name=name,
        args=args,
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
    渲染命令解析结果，供 channel 直接回复。
    """
    args = ", ".join(command.args) if command.args else "(none)"
    args_text = command.args_text if command.args_text else "(empty)"
    return "\n".join(
        [
            f"command: {command.name}",
            f"args: {args}",
            f"args_text: {args_text}",
        ]
    )


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
