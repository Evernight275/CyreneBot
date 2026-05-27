from __future__ import annotations

import pytest

from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.bot import BotConfigurationError
from cyreneAI.infra.adapters.channels.telegram import TelegramBotChannel
from cyreneAI.infra.bootstrap.registrations.telegram_bot_channel import (
    TELEGRAM_BOT_CHANNEL_DEFINITION,
    register_telegram_bot_channel,
)


def test_register_telegram_bot_channel_registers_definition_and_channel() -> None:
    registry = BotChannelRegistry()
    channel = TelegramBotChannel(bot_client=object())

    registered_channel = register_telegram_bot_channel(
        registry,
        channel=channel,
    )

    assert registered_channel is channel
    assert registry.get_definition("telegram") == TELEGRAM_BOT_CHANNEL_DEFINITION
    assert registry.get_channel("telegram") is channel


def test_register_telegram_bot_channel_requires_token_without_channel() -> None:
    with pytest.raises(BotConfigurationError):
        register_telegram_bot_channel(BotChannelRegistry())


def test_register_telegram_bot_channel_rejects_duplicate_registration() -> None:
    registry = BotChannelRegistry()
    register_telegram_bot_channel(
        registry,
        channel=TelegramBotChannel(bot_client=object()),
    )

    with pytest.raises(ConflictError):
        register_telegram_bot_channel(
            registry,
            channel=TelegramBotChannel(bot_client=object()),
        )
