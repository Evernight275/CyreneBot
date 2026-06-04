from __future__ import annotations

from typing import Any, cast

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

    async def get_me(self) -> dict[str, Any]:
        """
        调用 getMe。
        """
        return await self.request("getMe")

    async def set_webhook(
        self,
        *,
        url: str,
        secret_token: str | None = None,
        allowed_updates: list[str] | None = None,
        drop_pending_updates: bool | None = None,
    ) -> dict[str, Any]:
        """
        调用 setWebhook。
        """
        payload: dict[str, Any] = {
            "url": url,
        }
        if secret_token is not None:
            payload["secret_token"] = secret_token
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        if drop_pending_updates is not None:
            payload["drop_pending_updates"] = drop_pending_updates
        return await self.request("setWebhook", payload)

    async def delete_webhook(
        self,
        *,
        drop_pending_updates: bool = False,
    ) -> dict[str, Any]:
        """
        调用 deleteWebhook。
        """
        return await self.request(
            "deleteWebhook",
            {
                "drop_pending_updates": drop_pending_updates,
            },
        )

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        limit: int | None = None,
        timeout: int | None = None,
        allowed_updates: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        调用 getUpdates。
        """
        payload: dict[str, Any] = {}
        if offset is not None:
            payload["offset"] = offset
        if limit is not None:
            payload["limit"] = limit
        if timeout is not None:
            payload["timeout"] = timeout
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates

        result = await self.request("getUpdates", payload)
        updates = result.get("result")
        if not isinstance(updates, list):
            return []
        return [
            cast(dict[str, Any], update)
            for update in cast(list[Any], updates)
            if isinstance(update, dict)
        ]

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
            body = _parse_response_body(response)
            if not isinstance(body, dict):
                response.raise_for_status()
                raise TelegramBotAPIError("Telegram response body must be an object")
            response_body = cast(dict[str, Any], body)
            if response_body.get("ok") is not True:
                raise TelegramBotAPIError(
                    str(response_body.get("description") or "Telegram request failed"),
                    error_code=response_body.get("error_code"),
                    payload=response_body,
                )
            response.raise_for_status()
            result: Any = response_body.get("result")
            return (
                cast(dict[str, Any], result)
                if isinstance(result, dict)
                else {"result": result}
            )
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


def _parse_response_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        response.raise_for_status()
        raise TelegramBotAPIError("Telegram response body must be JSON") from exc
