from __future__ import annotations

import asyncio

import httpx
import pytest

from cyreneAI.core.errors.bot import BotActionError, BotConfigurationError
from cyreneAI.infra.adapters.channels.qq.client import QQBotClient


class FakeHTTPClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[dict] = []
        self.closed = False

    async def request(
        self,
        method: str,
        url: str,
        json: dict,
        headers: dict | None = None,
    ) -> httpx.Response:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "json": json,
                "headers": headers,
            }
        )
        return self.responses.pop(0)

    async def aclose(self) -> None:
        self.closed = True


def _response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=payload,
        request=httpx.Request("POST", "https://qq.example/test"),
    )


def test_qq_bot_client_requires_token_or_app_credentials() -> None:
    with pytest.raises(BotConfigurationError):
        QQBotClient()


def test_qq_bot_client_sends_request_with_direct_token() -> None:
    async def run() -> None:
        http_client = FakeHTTPClient([_response(200, {"id": "message-1"})])
        client = QQBotClient(
            token="token",
            base_url="https://qq.example",
            client=http_client,
        )

        result = await client.send_message(
            {
                "_route": "channel",
                "_route_id": "channel-1",
                "content": "pong",
            }
        )

        assert result == {"id": "message-1"}
        assert http_client.requests == [
            {
                "method": "POST",
                "url": "https://qq.example/channels/channel-1/messages",
                "json": {"content": "pong"},
                "headers": {"Authorization": "QQBot token"},
            }
        ]
        await client.close()
        assert http_client.closed is True

    asyncio.run(run())


def test_qq_bot_client_fetches_and_reuses_access_token() -> None:
    async def run() -> None:
        http_client = FakeHTTPClient(
            [
                _response(200, {"access_token": "access-token", "expires_in": 3600}),
                _response(200, {"id": "message-1"}),
                _response(200, {"id": "message-2"}),
            ]
        )
        client = QQBotClient(
            app_id="app-id",
            app_secret="app-secret",
            base_url="https://qq.example",
            token_url="https://bots.example/app/getAppAccessToken",
            client=http_client,
        )

        first = await client.send_message(
            {
                "_route": "group",
                "_route_id": "group-1",
                "content": "first",
            }
        )
        second = await client.send_message(
            {
                "_route": "user",
                "_route_id": "user-1",
                "content": "second",
            }
        )

        assert first == {"id": "message-1"}
        assert second == {"id": "message-2"}
        assert http_client.requests == [
            {
                "method": "POST",
                "url": "https://bots.example/app/getAppAccessToken",
                "json": {
                    "appId": "app-id",
                    "clientSecret": "app-secret",
                },
                "headers": None,
            },
            {
                "method": "POST",
                "url": "https://qq.example/v2/groups/group-1/messages",
                "json": {"content": "first"},
                "headers": {"Authorization": "QQBot access-token"},
            },
            {
                "method": "POST",
                "url": "https://qq.example/v2/users/user-1/messages",
                "json": {"content": "second"},
                "headers": {"Authorization": "QQBot access-token"},
            },
        ]

    asyncio.run(run())


def test_qq_bot_client_sends_dm_message() -> None:
    async def run() -> None:
        http_client = FakeHTTPClient([_response(200, {"id": "message-1"})])
        client = QQBotClient(
            token="token",
            base_url="https://qq.example",
            client=http_client,
        )

        result = await client.send_message(
            {
                "_route": "dm",
                "_route_id": "guild-1",
                "content": "pong",
                "msg_id": "message-1",
            }
        )

        assert result == {"id": "message-1"}
        assert http_client.requests == [
            {
                "method": "POST",
                "url": "https://qq.example/dms/guild-1/messages",
                "json": {"content": "pong", "msg_id": "message-1"},
                "headers": {"Authorization": "QQBot token"},
            }
        ]

    asyncio.run(run())


def test_qq_bot_client_translates_api_error() -> None:
    async def run() -> None:
        client = QQBotClient(
            token="token",
            client=FakeHTTPClient(
                [
                    _response(
                        200,
                        {
                            "code": 400,
                            "message": "Bad Request",
                        },
                    )
                ]
            ),
        )

        with pytest.raises(BotActionError):
            await client.send_message(
                {
                    "_route": "channel",
                    "_route_id": "channel-1",
                    "content": "pong",
                }
            )

    asyncio.run(run())


def test_qq_bot_client_includes_http_error_body_in_error_message() -> None:
    async def run() -> None:
        client = QQBotClient(
            token="token",
            client=FakeHTTPClient(
                [
                    _response(
                        400,
                        {
                            "code": 304023,
                            "message": "invalid msg_id",
                        },
                    )
                ]
            ),
        )

        with pytest.raises(BotActionError) as exc_info:
            await client.send_message(
                {
                    "_route": "channel",
                    "_route_id": "channel-1",
                    "content": "pong",
                }
            )

        assert "status 400" in str(exc_info.value)
        assert "path=/channels/channel-1/messages" in str(exc_info.value)
        assert "code=304023" in str(exc_info.value)
        assert "invalid msg_id" in str(exc_info.value)

    asyncio.run(run())
