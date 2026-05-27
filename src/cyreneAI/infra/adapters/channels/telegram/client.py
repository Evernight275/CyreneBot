from __future__ import annotations

from typing import Any

import httpx

from cyreneAI.core.errors.bot import BotConfigurationError
from cyreneAI.infra.adapters.channels.telegram.errors import (
    TelegramBotAPIError,
    raise_telegram_error,
)


class TelegramBotClient:
    """
    Telegram Bot API client。
    """

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.telegram.org",
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not token:
            raise BotConfigurationError("Telegram bot token is required")
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client

    async def send_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        调用 sendMessage。
        """
        return await self.request("sendMessage", payload)

    async def request(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        调用 Telegram Bot API 方法。
        """
        try:
            response = await self._request(method, payload or {})
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise TelegramBotAPIError("Telegram response body must be an object")
            if body.get("ok") is not True:
                raise TelegramBotAPIError(
                    str(body.get("description") or "Telegram request failed"),
                    error_code=body.get("error_code"),
                    payload=body,
                )
            result = body.get("result")
            return result if isinstance(result, dict) else {"result": result}
        except Exception as exc:
            raise_telegram_error(exc)

    async def close(self) -> None:
        """
        关闭持有的 HTTP client。
        """
        if self._client is not None:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        url = f"{self._base_url}/bot{self._token}/{method}"
        if self._client is not None:
            return await self._client.request("POST", url, json=payload)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.request("POST", url, json=payload)
