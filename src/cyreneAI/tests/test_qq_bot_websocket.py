from __future__ import annotations

import asyncio
import builtins
from types import SimpleNamespace

import pytest

from cyreneAI.core.errors.bot import BotConfigurationError
from cyreneAI.infra.adapters.channels.qq import websocket
from cyreneAI.infra.adapters.channels.qq.websocket import (
    QQBotWebSocketUpdateSource,
    _build_botpy_client,
    _message_to_update,
    _str_attr,
)


def test_qq_bot_websocket_maps_channel_message_object_to_update() -> None:
    update = _message_to_update(
        "AT_MESSAGE_CREATE",
        SimpleNamespace(
            id="message-1",
            content="hello",
            channel_id="channel-1",
            guild_id="guild-1",
            author=SimpleNamespace(id="user-1"),
            attachments=[],
        ),
    )

    assert update == {
        "id": "message-1",
        "t": "AT_MESSAGE_CREATE",
        "d": {
            "id": "message-1",
            "content": "hello",
            "channel_id": "channel-1",
            "guild_id": "guild-1",
            "author": {"id": "user-1"},
            "attachments": [],
        },
    }


def test_qq_bot_websocket_maps_group_message_object_to_update() -> None:
    update = _message_to_update(
        "GROUP_AT_MESSAGE_CREATE",
        SimpleNamespace(
            id="message-2",
            content="/help",
            channel_id="not-a-real-channel",
            group_openid="group-1",
            author=SimpleNamespace(member_openid="user-2"),
        ),
    )

    assert update["t"] == "GROUP_AT_MESSAGE_CREATE"
    assert "channel_id" not in update["d"]
    assert update["d"]["group_openid"] == "group-1"
    assert update["d"]["user_openid"] == "user-2"
    assert update["d"]["author"]["id"] == "user-2"


def test_qq_bot_websocket_maps_direct_message_object_to_update() -> None:
    update = _message_to_update(
        "DIRECT_MESSAGE_CREATE",
        SimpleNamespace(
            id="message-3",
            content="hello",
            channel_id="dm-channel-1",
            guild_id="guild-1",
            author=SimpleNamespace(id="user-3"),
        ),
    )

    assert update == {
        "id": "message-3",
        "t": "DIRECT_MESSAGE_CREATE",
        "d": {
            "id": "message-3",
            "content": "hello",
            "channel_id": "dm-channel-1",
            "guild_id": "guild-1",
            "author": {"id": "user-3"},
        },
    }


def test_qq_bot_websocket_maps_c2c_sender_to_update() -> None:
    update = _message_to_update(
        "C2C_MESSAGE_CREATE",
        SimpleNamespace(
            id="message-4",
            content="hello",
            user_openid="route-user",
            sender=SimpleNamespace(user_id="sender-1"),
        ),
    )

    assert update == {
        "id": "message-4",
        "t": "C2C_MESSAGE_CREATE",
        "d": {
            "id": "message-4",
            "content": "hello",
            "user_openid": "route-user",
            "user_id": "sender-1",
            "author": {"id": "sender-1"},
        },
    }


def test_qq_bot_websocket_str_attr_handles_missing_and_none() -> None:
    assert _str_attr(None, "id") == ""
    assert _str_attr(SimpleNamespace(id=None), "id") == ""
    assert _str_attr(SimpleNamespace(id=123), "id") == "123"


def test_qq_bot_websocket_builds_client_callbacks() -> None:
    updates: list[dict] = []

    async def handler(update: dict) -> None:
        updates.append(update)

    class BaseClient:
        def __init__(self, *, intents, bot_log: bool, timeout: float) -> None:
            self.intents = intents
            self.bot_log = bot_log
            self.timeout = timeout

    async def run() -> None:
        client = _build_botpy_client(
            client_cls=BaseClient,
            intents="intents",
            timeout=9.5,
            handler=handler,
        )

        assert isinstance(client, BaseClient)
        assert client.intents == "intents"
        assert client.bot_log is False
        assert client.timeout == 9.5

        await client.on_at_message_create(SimpleNamespace(id="a", content="at"))
        await client.on_group_at_message_create(
            SimpleNamespace(id="g", content="group")
        )
        await client.on_direct_message_create(
            SimpleNamespace(id="d", content="direct")
        )
        await client.on_c2c_message_create(SimpleNamespace(id="c", content="c2c"))

    asyncio.run(run())

    assert [update["t"] for update in updates] == [
        "AT_MESSAGE_CREATE",
        "GROUP_AT_MESSAGE_CREATE",
        "DIRECT_MESSAGE_CREATE",
        "C2C_MESSAGE_CREATE",
    ]


def test_qq_bot_websocket_source_runs_and_closes_with_shutdown(monkeypatch) -> None:
    created_clients: list[object] = []

    class FakeBotpy:
        class Intents:
            def __init__(
                self,
                *,
                public_messages: bool,
                public_guild_messages: bool,
                direct_message: bool,
            ) -> None:
                self.public_messages = public_messages
                self.public_guild_messages = public_guild_messages
                self.direct_message = direct_message

    class FakeClient:
        def __init__(self, *, intents, bot_log: bool, timeout: float) -> None:
            self.intents = intents
            self.bot_log = bot_log
            self.timeout = timeout
            self.started_with: dict[str, str] | None = None
            self.shutdown_called = False
            created_clients.append(self)

        async def start(self, *, appid: str, secret: str) -> None:
            self.started_with = {"appid": appid, "secret": secret}

        async def shutdown(self) -> None:
            self.shutdown_called = True

    async def handler(update: dict) -> None:
        return None

    async def run() -> None:
        monkeypatch.setattr(
            websocket,
            "_load_botpy",
            lambda: (FakeBotpy, FakeClient),
        )
        source = QQBotWebSocketUpdateSource(
            app_id="app-id",
            app_secret="secret",
            enable_group_c2c=False,
            enable_guild_direct_message=False,
            timeout=7,
        )

        await source.run(handler)
        await source.close()

    asyncio.run(run())

    assert len(created_clients) == 1
    client = created_clients[0]
    assert client.intents.public_messages is False
    assert client.intents.public_guild_messages is True
    assert client.intents.direct_message is False
    assert client.timeout == 7
    assert client.started_with == {"appid": "app-id", "secret": "secret"}
    assert client.shutdown_called is True


def test_qq_bot_websocket_source_close_uses_close_when_shutdown_missing() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    async def run() -> None:
        source = QQBotWebSocketUpdateSource(app_id="app-id", app_secret="secret")
        client = FakeClient()
        source._client = client

        await source.close()

        assert client.closed is True

    asyncio.run(run())


def test_qq_bot_websocket_source_close_without_client_is_noop() -> None:
    async def run() -> None:
        source = QQBotWebSocketUpdateSource(app_id="app-id", app_secret="secret")
        await source.close()

    asyncio.run(run())


def test_qq_bot_websocket_load_botpy_reports_missing_dependency(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "botpy":
            raise ModuleNotFoundError("No module named 'botpy'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(BotConfigurationError, match="requires qq-botpy"):
        websocket._load_botpy()
