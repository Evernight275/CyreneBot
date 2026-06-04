from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from cyreneAI.core.errors.bot import BotConfigurationError


QQWebSocketUpdateHandler = Callable[[dict[str, Any]], Awaitable[None]]


class QQBotWebSocketUpdateSource:
    """
    QQ official botpy websocket update source.
    """

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        enable_group_c2c: bool = True,
        enable_guild_direct_message: bool = True,
        timeout: float = 20.0,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._enable_group_c2c = enable_group_c2c
        self._enable_guild_direct_message = enable_guild_direct_message
        self._timeout = timeout
        self._client: Any | None = None

    async def run(self, handler: QQWebSocketUpdateHandler) -> None:
        botpy, client_cls = _load_botpy()
        intents = botpy.Intents(
            public_messages=self._enable_group_c2c,
            public_guild_messages=True,
            direct_message=self._enable_guild_direct_message,
        )
        client = _build_botpy_client(
            client_cls=client_cls,
            intents=intents,
            timeout=self._timeout,
            handler=handler,
        )
        self._client = client
        result = client.start(appid=self._app_id, secret=self._app_secret)
        if inspect.isawaitable(result):
            await result

    async def close(self) -> None:
        if self._client is None:
            return
        shutdown = getattr(self._client, "shutdown", None)
        if shutdown is not None:
            result = shutdown()
            if inspect.isawaitable(result):
                await result
            return
        close = getattr(self._client, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result


def _build_botpy_client(
    *,
    client_cls: type,
    intents: Any,
    timeout: float,
    handler: QQWebSocketUpdateHandler,
) -> Any:
    class CyreneQQBotPyClient(client_cls):  # type: ignore[misc, valid-type]
        async def on_at_message_create(self, message: Any) -> None:
            await handler(_message_to_update("AT_MESSAGE_CREATE", message))

        async def on_group_at_message_create(self, message: Any) -> None:
            await handler(_message_to_update("GROUP_AT_MESSAGE_CREATE", message))

        async def on_direct_message_create(self, message: Any) -> None:
            await handler(_message_to_update("DIRECT_MESSAGE_CREATE", message))

        async def on_c2c_message_create(self, message: Any) -> None:
            await handler(_message_to_update("C2C_MESSAGE_CREATE", message))

    return CyreneQQBotPyClient(
        intents=intents,
        bot_log=False,
        timeout=timeout,
    )


def _message_to_update(event_type: str, message: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": _str_attr(message, "id"),
        "content": _str_attr(message, "content"),
    }
    for attr in (
        "channel_id",
        "guild_id",
        "group_id",
        "group_openid",
        "user_id",
        "user_openid",
    ):
        value = _str_attr(message, attr)
        if value:
            data[attr] = value

    author = getattr(message, "author", None)
    author_id = (
        _str_attr(author, "id")
        or _str_attr(author, "user_openid")
        or _str_attr(author, "member_openid")
    )
    if author_id:
        data["author"] = {"id": author_id}
        if event_type in {"GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE"}:
            data["user_openid"] = author_id

    sender = getattr(message, "sender", None)
    sender_id = _str_attr(sender, "user_id") or _str_attr(sender, "id")
    if sender_id:
        data["user_id"] = sender_id
        data.setdefault("author", {"id": sender_id})

    attachments = getattr(message, "attachments", None)
    if attachments is not None:
        data["attachments"] = attachments

    return {
        "id": data["id"],
        "t": event_type,
        "d": data,
    }


def _str_attr(source: Any, name: str) -> str:
    if source is None:
        return ""
    value = getattr(source, name, "")
    if value is None:
        return ""
    return str(value)


def _load_botpy() -> tuple[Any, type]:
    try:
        import botpy
        from botpy import Client
    except ModuleNotFoundError as exc:
        raise BotConfigurationError(
            "QQ websocket mode requires qq-botpy. Install the dev dependencies "
            "or add qq-botpy to the runtime environment."
        ) from exc
    return botpy, Client
