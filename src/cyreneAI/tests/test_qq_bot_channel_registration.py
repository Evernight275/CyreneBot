from __future__ import annotations

import pytest

from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.bot import BotConfigurationError
from cyreneAI.infra.adapters.channels.qq import QQBotChannel
from cyreneAI.infra.bootstrap.registrations.qq_bot_channel import (
    QQ_BOT_CHANNEL_DEFINITION,
    register_qq_bot_channel,
)


def test_register_qq_bot_channel_registers_definition_and_channel() -> None:
    registry = BotChannelRegistry()
    channel = QQBotChannel(bot_client=object())

    registered_channel = register_qq_bot_channel(
        registry,
        channel=channel,
    )

    assert registered_channel is channel
    assert registry.get_definition("qq") == QQ_BOT_CHANNEL_DEFINITION
    assert registry.get_channel("qq") is channel


def test_register_qq_bot_channel_requires_credentials_without_channel() -> None:
    with pytest.raises(BotConfigurationError):
        register_qq_bot_channel(BotChannelRegistry())


def test_register_qq_bot_channel_accepts_app_credentials_without_token() -> None:
    registry = BotChannelRegistry()

    channel = register_qq_bot_channel(
        registry,
        app_id="app-id",
        app_secret="app-secret",
    )

    assert registry.get_channel("qq") is channel


def test_register_qq_bot_channel_rejects_duplicate_registration() -> None:
    registry = BotChannelRegistry()
    register_qq_bot_channel(
        registry,
        channel=QQBotChannel(bot_client=object()),
    )

    with pytest.raises(ConflictError):
        register_qq_bot_channel(
            registry,
            channel=QQBotChannel(bot_client=object()),
        )
