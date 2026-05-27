from __future__ import annotations

import asyncio

import httpx
import pytest

from cyreneAI.core.errors.bot import BotActionError, BotConfigurationError
from cyreneAI.infra.adapters.channels.telegram.client import TelegramBotClient


class FakeHTTPClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.requests: list[dict] = []
        self.closed = False

    async def request(self, method: str, url: str, json: dict) -> httpx.Response:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "json": json,
            }
        )
        return self.response

    async def aclose(self) -> None:
        self.closed = True


def _response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=payload,
        request=httpx.Request("POST", "https://telegram.example/test"),
    )


def test_telegram_bot_client_requires_token() -> None:
    with pytest.raises(BotConfigurationError):
        TelegramBotClient("")


def test_telegram_bot_client_sends_request() -> None:
    async def run() -> None:
        http_client = FakeHTTPClient(
            _response(
                200,
                {
                    "ok": True,
                    "result": {"message_id": 1},
                },
            )
        )
        client = TelegramBotClient(
            "token",
            base_url="https://telegram.example",
            client=http_client,
        )

        result = await client.send_message(
            {
                "chat_id": "99",
                "text": "pong",
            }
        )

        assert result == {"message_id": 1}
        assert http_client.requests == [
            {
                "method": "POST",
                "url": "https://telegram.example/bottoken/sendMessage",
                "json": {
                    "chat_id": "99",
                    "text": "pong",
                },
            }
        ]
        await client.close()
        assert http_client.closed is True

    asyncio.run(run())


def test_telegram_bot_client_translates_api_error() -> None:
    async def run() -> None:
        client = TelegramBotClient(
            "token",
            client=FakeHTTPClient(
                _response(
                    200,
                    {
                        "ok": False,
                        "error_code": 400,
                        "description": "Bad Request",
                    },
                )
            ),
        )

        with pytest.raises(BotActionError):
            await client.send_message({"chat_id": "99", "text": "pong"})

    asyncio.run(run())
