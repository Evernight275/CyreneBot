from __future__ import annotations

from typing import Any

import httpx

from cyreneAI.core.errors.bot import BotConfigurationError
from cyreneAI.core.schema.bot import BotAction, BotEvent
from cyreneAI.infra.adapters.channels.telegram.client import TelegramBotClient
from cyreneAI.infra.adapters.channels.telegram.mapper import (
    map_bot_action_to_send_message_payload,
    map_telegram_update_to_bot_event,
)


class TelegramBotChannel:
    """
    Telegram bot channel adapter。
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        channel_id: str = "telegram",
        base_url: str = "https://api.telegram.org",
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
        bot_client: TelegramBotClient | None = None,
    ) -> None:
        if bot_client is None and not token:
            raise BotConfigurationError("Telegram bot token is required")
        self.channel_id = channel_id
        self._client = bot_client or TelegramBotClient(
            token=token or "",
            base_url=base_url,
            timeout=timeout,
            client=client,
        )

    def map_update(self, update: dict[str, Any]) -> BotEvent:
        """
        将 Telegram update 映射为标准 BotEvent。
        """
        return map_telegram_update_to_bot_event(
            update,
            channel_id=self.channel_id,
        )

    async def send(self, action: BotAction) -> None:
        """
        发送标准 BotAction 到 Telegram。
        """
        payload = map_bot_action_to_send_message_payload(action)
        await self._client.send_message(payload)

    async def poll_events(
        self,
        *,
        offset: int | None = None,
        limit: int | None = None,
        timeout: int | None = None,
        allowed_updates: list[str] | None = None,
    ) -> list[BotEvent]:
        """
        通过 Telegram getUpdates 拉取并映射事件。
        """
        updates = await self._client.get_updates(
            offset=offset,
            limit=limit,
            timeout=timeout,
            allowed_updates=allowed_updates,
        )
        return [self.map_update(update) for update in updates]

    async def close(self) -> None:
        """
        关闭 channel 持有的外部资源。
        """
        close = getattr(self._client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
