from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from cyreneAI.core.errors.bot import BotConfigurationError
from cyreneAI.core.schema.bot import BotAction, BotEvent
from cyreneAI.infra.adapters.channels.qq.client import QQBotClient
from cyreneAI.infra.adapters.channels.qq.mapper import (
    map_bot_action_to_qq_send_message_payload,
    map_qq_update_to_bot_event,
)
from cyreneAI.infra.adapters.channels.qq.websocket import QQBotWebSocketUpdateSource

QQWebSocketUpdateHandler = Callable[[dict[str, Any]], Awaitable[None]]


class QQBotChannel:
    """
    QQ bot channel adapter.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        app_id: str | None = None,
        app_secret: str | None = None,
        channel_id: str = "qq",
        base_url: str = "https://api.sgroup.qq.com",
        token_url: str = "https://bots.qq.com/app/getAppAccessToken",
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
        bot_client: QQBotClient | None = None,
        websocket_source: QQBotWebSocketUpdateSource | None = None,
    ) -> None:
        if bot_client is None and not token and not (app_id and app_secret):
            raise BotConfigurationError("QQ bot token or app_id/app_secret is required")
        self.channel_id = channel_id
        self._client = bot_client or QQBotClient(
            token=token,
            app_id=app_id,
            app_secret=app_secret,
            base_url=base_url,
            token_url=token_url,
            timeout=timeout,
            client=client,
        )
        self._websocket_source = websocket_source
        if self._websocket_source is None and app_id and app_secret:
            self._websocket_source = QQBotWebSocketUpdateSource(
                app_id=app_id,
                app_secret=app_secret,
            )

    def map_update(self, update: dict[str, Any]) -> BotEvent:
        """
        Map a QQ update to a standard BotEvent.
        """
        return map_qq_update_to_bot_event(
            update,
            channel_id=self.channel_id,
        )

    async def send(self, action: BotAction) -> None:
        """
        Send a standard BotAction to QQ.
        """
        payload = map_bot_action_to_qq_send_message_payload(action)
        await self._client.send_message(payload)

    async def run_websocket(self, handler: QQWebSocketUpdateHandler) -> None:
        """
        Run QQ official websocket updates until the client closes.
        """
        if self._websocket_source is None:
            raise BotConfigurationError(
                "QQ websocket mode requires app_id/app_secret credentials"
            )
        await self._websocket_source.run(handler)

    async def close_websocket(self) -> None:
        """
        Close the QQ websocket update source, if it is running.
        """
        if self._websocket_source is not None:
            await self._websocket_source.close()

    async def close(self) -> None:
        """
        Close external resources held by the channel.
        """
        await self.close_websocket()
        close = getattr(self._client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
