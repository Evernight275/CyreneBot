from __future__ import annotations

from typing import Any

from cyreneAI.core.errors.bot import BotActionError, BotInputError
from cyreneAI.core.schema.bot import (
    BotAction,
    BotActionType,
    BotEvent,
    BotEventType,
    BotMessage,
)
from cyreneAI.core.schema.message import ContentPart, ContentPartType


def map_telegram_update_to_bot_event(
    update: dict[str, Any],
    *,
    channel_id: str = "telegram",
) -> BotEvent:
    """
    将 Telegram update 映射为标准 BotEvent。
    """
    update_id = str(update.get("update_id", ""))
    message = update.get("message")
    if not isinstance(message, dict):
        return BotEvent(
            event_id=update_id,
            event_type=BotEventType.UNKNOWN,
            channel_id=channel_id,
            session_id=f"{channel_id}:unknown:{update_id}",
            metadata={"telegram_update_id": update_id},
        )

    chat = message.get("chat")
    if not isinstance(chat, dict) or chat.get("id") is None:
        raise BotInputError("Telegram message update must include chat.id")

    chat_id = str(chat["id"])
    sender = message.get("from")
    user_id = (
        str(sender["id"])
        if isinstance(sender, dict) and sender.get("id") is not None
        else None
    )
    text = _message_text(message)
    event_type = (
        BotEventType.COMMAND
        if text is not None and text.strip().startswith("/")
        else BotEventType.MESSAGE
    )
    message_id = (
        str(message["message_id"])
        if message.get("message_id") is not None
        else None
    )

    return BotEvent(
        event_id=update_id,
        event_type=event_type,
        channel_id=channel_id,
        session_id=f"{channel_id}:{chat_id}",
        user_id=user_id,
        thread_id=chat_id,
        message=BotMessage(
            message_id=message_id,
            sender_id=user_id,
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=text or "",
                )
            ],
            metadata={
                "telegram_chat_id": chat_id,
                "telegram_chat_type": str(chat.get("type") or ""),
            },
        ),
        metadata={
            "telegram_update_id": update_id,
            "telegram_chat_id": chat_id,
            "telegram_chat_type": str(chat.get("type") or ""),
        },
    )


def map_bot_action_to_send_message_payload(action: BotAction) -> dict[str, Any]:
    """
    将标准 BotAction 映射为 Telegram sendMessage payload。
    """
    if action.action_type != BotActionType.SEND_MESSAGE:
        raise BotActionError(
            f"Telegram channel does not support action {action.action_type}"
        )

    chat_id = _resolve_chat_id(action)
    text = _action_text(action)
    if not text:
        raise BotActionError("Telegram sendMessage action must include text")

    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
    }
    if action.thread_id and action.thread_id != chat_id:
        payload["message_thread_id"] = action.thread_id
    return payload


def _message_text(message: dict[str, Any]) -> str | None:
    text = message.get("text")
    if isinstance(text, str):
        return text
    caption = message.get("caption")
    if isinstance(caption, str):
        return caption
    return None


def _resolve_chat_id(action: BotAction) -> str:
    telegram_chat_id = action.metadata.get("telegram_chat_id")
    if telegram_chat_id:
        return str(telegram_chat_id)
    if action.thread_id:
        return action.thread_id
    if action.recipient_id:
        return action.recipient_id
    prefix = f"{action.channel_id}:"
    if action.session_id.startswith(prefix):
        return action.session_id.removeprefix(prefix)
    raise BotActionError("Telegram action must include chat id")


def _action_text(action: BotAction) -> str:
    if action.message is None:
        return ""
    chunks = [
        part.text
        for part in action.message.content
        if part.type == ContentPartType.TEXT and part.text
    ]
    return "\n".join(chunks)
