from __future__ import annotations

from typing import Any, cast

from cyreneAI.core.errors.bot import BotActionError, BotInputError
from cyreneAI.core.schema.bot import (
    BotAction,
    BotActionType,
    BotEvent,
    BotEventType,
    BotMessage,
)
from cyreneAI.core.schema.message import ContentPart, ContentPartType


QQ_MESSAGE_EVENT_TYPES = {
    "AT_MESSAGE_CREATE",
    "C2C_MESSAGE_CREATE",
    "DIRECT_MESSAGE_CREATE",
    "GROUP_AT_MESSAGE_CREATE",
    "MESSAGE_CREATE",
}


def map_qq_update_to_bot_event(
    update: dict[str, Any],
    *,
    channel_id: str = "qq",
) -> BotEvent:
    """
    Map a QQ webhook/gateway update to a standard BotEvent.
    """
    event_name = _event_name(update)
    data = _event_data(update)
    event_id = _event_id(update, data)
    if not _is_message_event(event_name, data):
        return BotEvent(
            event_id=event_id,
            event_type=BotEventType.UNKNOWN,
            channel_id=channel_id,
            session_id=f"{channel_id}:unknown:{event_id}",
            metadata=_event_metadata(
                update=update,
                data=data,
                event_name=event_name,
            ),
        )

    route = _resolve_route(data, event_name=event_name)
    text = _message_text(data)
    event_type = (
        BotEventType.COMMAND
        if text is not None and text.strip().startswith("/")
        else BotEventType.MESSAGE
    )
    user_id = _user_id(data)
    message_id = _message_id(data)
    metadata = _event_metadata(
        update=update,
        data=data,
        event_name=event_name,
    )

    return BotEvent(
        event_id=event_id,
        event_type=event_type,
        channel_id=channel_id,
        session_id=f"{channel_id}:{route.kind}:{route.value}",
        user_id=user_id,
        thread_id=route.value,
        message=BotMessage(
            message_id=message_id,
            sender_id=user_id,
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=text or "",
                )
            ],
            metadata=metadata,
        ),
        metadata=metadata,
    )


def map_bot_action_to_qq_send_message_payload(action: BotAction) -> dict[str, Any]:
    """
    Map a standard SEND_MESSAGE action to a QQ send payload.
    """
    if action.action_type != BotActionType.SEND_MESSAGE:
        raise BotActionError(f"QQ channel does not support action {action.action_type}")

    text = _action_text(action)
    if not text:
        raise BotActionError("QQ send message action must include text")

    route_kind, route_value = _resolve_action_route(action)
    payload: dict[str, Any] = {
        "content": text,
        "_route": route_kind,
        "_route_id": route_value,
    }
    if route_kind in {"group", "user"}:
        payload["msg_type"] = 0
    message_id = _metadata_str(action.metadata.get("qq_message_id"))
    if message_id is not None:
        payload["msg_id"] = message_id
        if route_kind in {"group", "user"}:
            payload["msg_seq"] = _action_msg_seq(action)
    return payload


class _Route:
    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value


def _event_name(update: dict[str, Any]) -> str:
    raw = update.get("t") or update.get("event_type") or update.get("type")
    return str(raw or "")


def _event_data(update: dict[str, Any]) -> dict[str, Any]:
    data = update.get("d") or update.get("data")
    if isinstance(data, dict):
        return cast(dict[str, Any], data)
    return update


def _event_id(update: dict[str, Any], data: dict[str, Any]) -> str:
    value = (
        update.get("id")
        or update.get("event_id")
        or update.get("s")
        or data.get("id")
        or data.get("message_id")
        or ""
    )
    return str(value)


def _is_message_event(event_name: str, data: dict[str, Any]) -> bool:
    if event_name in QQ_MESSAGE_EVENT_TYPES:
        return True
    return _message_text(data) is not None and any(
        data.get(key) is not None
        for key in (
            "channel_id",
            "group_id",
            "group_openid",
            "guild_id",
            "user_openid",
            "user_id",
        )
    )


def _resolve_route(data: dict[str, Any], *, event_name: str = "") -> _Route:
    if event_name == "GROUP_AT_MESSAGE_CREATE":
        group_route = _group_route(data)
        if group_route is not None:
            return group_route
    if event_name == "C2C_MESSAGE_CREATE":
        user_route = _user_route(data)
        if user_route is not None:
            return user_route
    if event_name == "DIRECT_MESSAGE_CREATE":
        dm_route = _direct_message_route(data)
        if dm_route is not None:
            return dm_route

    channel_id = _metadata_str(data.get("channel_id"))
    if channel_id is not None:
        return _Route("channel", channel_id)
    group_route = _group_route(data)
    if group_route is not None:
        return group_route
    user_route = _user_route(data)
    if user_route is not None:
        return user_route
    guild_id = _metadata_str(data.get("guild_id"))
    if guild_id is not None:
        return _Route("guild", guild_id)

    author = data.get("author")
    if isinstance(author, dict):
        author_id = _metadata_str(cast(dict[str, Any], author).get("id"))
        if author_id is not None:
            return _Route("user", author_id)

    raise BotInputError(
        "QQ message update must include channel_id, group_id, group_openid, "
        "guild_id, user_id, or user_openid"
    )


def _group_route(data: dict[str, Any]) -> _Route | None:
    group_id = _metadata_str(data.get("group_openid")) or _metadata_str(
        data.get("group_id")
    )
    if group_id is None:
        return None
    return _Route("group", group_id)


def _user_route(data: dict[str, Any]) -> _Route | None:
    user_id = (
        _metadata_str(data.get("user_openid"))
        or _metadata_str(data.get("user_id"))
        or _metadata_str(data.get("openid"))
    )
    if user_id is None:
        return None
    return _Route("user", user_id)


def _direct_message_route(data: dict[str, Any]) -> _Route | None:
    guild_id = _metadata_str(data.get("guild_id"))
    if guild_id is None:
        return None
    return _Route("dm", guild_id)


def _message_text(data: dict[str, Any]) -> str | None:
    content = data.get("content")
    if isinstance(content, str):
        return content
    text = data.get("text")
    if isinstance(text, str):
        return text
    return None


def _message_id(data: dict[str, Any]) -> str | None:
    return _metadata_str(data.get("id")) or _metadata_str(data.get("message_id"))


def _user_id(data: dict[str, Any]) -> str | None:
    author = data.get("author")
    if isinstance(author, dict):
        author_id = _metadata_str(cast(dict[str, Any], author).get("id"))
        if author_id is not None:
            return author_id
    member = data.get("member")
    if isinstance(member, dict):
        user = cast(dict[str, Any], member).get("user")
        if isinstance(user, dict):
            user_id = _metadata_str(cast(dict[str, Any], user).get("id"))
            if user_id is not None:
                return user_id
    return (
        _metadata_str(data.get("user_openid"))
        or _metadata_str(data.get("user_id"))
        or _metadata_str(data.get("openid"))
    )


def _event_metadata(
    *,
    update: dict[str, Any],
    data: dict[str, Any],
    event_name: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "qq_event_type": event_name,
    }
    for source, target in (
        ("id", "qq_message_id"),
        ("message_id", "qq_message_id"),
        ("channel_id", "qq_channel_id"),
        ("guild_id", "qq_guild_id"),
        ("group_id", "qq_group_id"),
        ("group_openid", "qq_group_openid"),
        ("user_id", "qq_user_id"),
        ("user_openid", "qq_user_openid"),
    ):
        value = _metadata_str(data.get(source))
        if value is not None:
            metadata[target] = value
    sequence = update.get("s")
    if isinstance(sequence, int) and not isinstance(sequence, bool):
        metadata["qq_sequence"] = sequence
    return metadata


def _resolve_action_route(action: BotAction) -> tuple[str, str]:
    event_type = _metadata_str(action.metadata.get("qq_event_type"))
    if event_type == "GROUP_AT_MESSAGE_CREATE":
        route = _resolve_action_route_from_keys(
            action,
            (
                ("qq_group_openid", "group"),
                ("qq_group_id", "group"),
            ),
        )
        if route is not None:
            return route
    if event_type == "C2C_MESSAGE_CREATE":
        route = _resolve_action_route_from_keys(
            action,
            (
                ("qq_user_openid", "user"),
                ("qq_user_id", "user"),
            ),
        )
        if route is not None:
            return route
    if event_type == "DIRECT_MESSAGE_CREATE":
        route = _resolve_action_route_from_keys(
            action,
            (
                ("qq_guild_id", "dm"),
            ),
        )
        if route is not None:
            return route

    for key, route in (
        ("qq_channel_id", "channel"),
        ("qq_group_openid", "group"),
        ("qq_group_id", "group"),
        ("qq_user_openid", "user"),
        ("qq_user_id", "user"),
    ):
        value = _metadata_str(action.metadata.get(key))
        if value is not None:
            return route, value

    parsed = _parse_session_route(action.session_id)
    if parsed is not None:
        return parsed
    if action.thread_id:
        parsed = _parse_session_route(action.thread_id)
        if parsed is not None:
            return parsed
    if action.thread_id:
        return "channel", action.thread_id
    if action.recipient_id:
        return "user", action.recipient_id
    raise BotActionError("QQ action must include a channel, group, or user route")


def _resolve_action_route_from_keys(
    action: BotAction,
    keys: tuple[tuple[str, str], ...],
) -> tuple[str, str] | None:
    for key, route in keys:
        value = _metadata_str(action.metadata.get(key))
        if value is not None:
            return route, value
    return None


def _parse_session_route(value: str) -> tuple[str, str] | None:
    parts = value.split(":", maxsplit=2)
    if len(parts) == 3 and parts[0] == "qq" and parts[1] in {
        "channel",
        "dm",
        "group",
        "user",
        "guild",
    }:
        route = "channel" if parts[1] == "guild" else parts[1]
        return route, parts[2]
    return None


def _action_text(action: BotAction) -> str:
    if action.message is None:
        return ""
    chunks = [
        part.text
        for part in action.message.content
        if part.type == ContentPartType.TEXT and part.text
    ]
    return "\n".join(chunks)


def _action_msg_seq(action: BotAction) -> int:
    value = action.metadata.get("qq_msg_seq")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return 1
        return parsed
    return 1


def _metadata_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None
