from __future__ import annotations

import asyncio

import pytest

from cyreneAI.core.errors.bot import BotConfigurationError
from cyreneAI.core.schema.bot import BotAction, BotActionType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.infra.adapters.channels.qq import QQBotChannel


class FakeQQClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self.downloads: list[dict] = []
        self.closed = False

    async def send_message(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {"id": "message-2"}

    async def download_attachment(
        self,
        url: str,
        *,
        max_bytes: int,
    ) -> tuple[bytes, str]:
        self.downloads.append(
            {
                "url": url,
                "max_bytes": max_bytes,
            }
        )
        return b"image-bytes", "image/png"

    async def close(self) -> None:
        self.closed = True


class FakeQQWebSocketSource:
    def __init__(self) -> None:
        self.handler = None
        self.closed = False

    async def run(self, handler) -> None:
        self.handler = handler
        await handler(
            {
                "t": "AT_MESSAGE_CREATE",
                "d": {
                    "id": "message-1",
                    "channel_id": "channel-1",
                    "author": {"id": "user-1"},
                    "content": "hello",
                },
            }
        )

    async def close(self) -> None:
        self.closed = True


def _action(text: str = "pong") -> BotAction:
    return BotAction(
        action_type=BotActionType.SEND_MESSAGE,
        channel_id="qq",
        session_id="qq:channel:channel-1",
        thread_id="channel-1",
        message=BotMessage(
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=text,
                )
            ]
        ),
    )


def test_qq_bot_channel_requires_credentials_without_client() -> None:
    with pytest.raises(BotConfigurationError):
        QQBotChannel()


def test_qq_bot_channel_accepts_app_credentials_without_token() -> None:
    channel = QQBotChannel(app_id="app-id", app_secret="app-secret")

    assert channel.channel_id == "qq"


def test_qq_bot_channel_sends_message_action() -> None:
    async def run() -> None:
        client = FakeQQClient()
        channel = QQBotChannel(bot_client=client)

        await channel.send(_action())

        assert client.payloads == [
            {
                "content": "pong",
                "_route": "channel",
                "_route_id": "channel-1",
            }
        ]
        await channel.close()
        assert client.closed is True

    asyncio.run(run())


def test_qq_bot_channel_maps_update() -> None:
    channel = QQBotChannel(bot_client=FakeQQClient())

    event = channel.map_update(
        {
            "t": "AT_MESSAGE_CREATE",
            "d": {
                "id": "message-1",
                "channel_id": "channel-1",
                "author": {"id": "user-1"},
                "content": "hello",
            },
        }
    )

    assert event.session_id == "qq:channel:channel-1"
    assert event.message is not None
    assert event.message.content[0].text == "hello"


def test_qq_bot_channel_async_map_downloads_image_attachment() -> None:
    async def run() -> None:
        client = FakeQQClient()
        channel = QQBotChannel(
            bot_client=client,
            max_attachment_bytes=1024,
        )

        event = await channel.map_update_async(
            {
                "t": "GROUP_AT_MESSAGE_CREATE",
                "d": {
                    "id": "message-1",
                    "group_openid": "group-1",
                    "user_openid": "user-1",
                    "content": "look",
                    "attachments": [
                        {
                            "id": "attachment-1",
                            "filename": "cat.png",
                            "content_type": "image/png",
                            "url": "https://qq.example/cat.png",
                        }
                    ],
                },
            }
        )

        assert client.downloads == [
            {
                "url": "https://qq.example/cat.png",
                "max_bytes": 1024,
            }
        ]
        assert event.message is not None
        image_part = event.message.content[1]
        assert image_part.type == ContentPartType.IMAGE
        assert image_part.data == "aW1hZ2UtYnl0ZXM="
        assert image_part.mime_type == "image/png"
        assert image_part.metadata["qq_attachment_downloaded"] is True

    asyncio.run(run())


def test_qq_bot_channel_runs_websocket_source() -> None:
    async def run() -> None:
        source = FakeQQWebSocketSource()
        channel = QQBotChannel(
            bot_client=FakeQQClient(),
            websocket_source=source,
        )
        updates = []

        async def handle_update(update):
            updates.append(update)

        await channel.run_websocket(handle_update)
        await channel.close()

        assert len(updates) == 1
        assert updates[0]["d"]["content"] == "hello"
        assert source.closed is True

    asyncio.run(run())


def test_qq_bot_channel_requires_app_credentials_for_websocket() -> None:
    async def run() -> None:
        channel = QQBotChannel(
            token="access-token",
            bot_client=FakeQQClient(),
        )

        with pytest.raises(BotConfigurationError):
            await channel.run_websocket(lambda update: None)

    asyncio.run(run())
