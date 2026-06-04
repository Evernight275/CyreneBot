from __future__ import annotations

from types import SimpleNamespace

from cyreneAI.infra.adapters.channels.qq.websocket import _message_to_update


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
            group_openid="group-1",
            author=SimpleNamespace(member_openid="user-2"),
        ),
    )

    assert update["t"] == "GROUP_AT_MESSAGE_CREATE"
    assert update["d"]["group_openid"] == "group-1"
    assert update["d"]["user_openid"] == "user-2"
    assert update["d"]["author"]["id"] == "user-2"
