from __future__ import annotations

import pytest

from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.errors.base import ConflictError
from cyreneAI.infra.adapters.channels.memory import InMemoryBotChannel
from cyreneAI.infra.bootstrap.registrations.bot_channels import (
    register_default_bot_channels,
)
from cyreneAI.infra.bootstrap.registrations.memory_bot_channel import (
    MEMORY_BOT_CHANNEL_DEFINITION,
    register_memory_bot_channel,
)


def test_register_memory_bot_channel_registers_definition_and_channel() -> None:
    registry = BotChannelRegistry()
    channel = InMemoryBotChannel()

    registered_channel = register_memory_bot_channel(registry, channel)

    assert registered_channel is channel
    assert registry.get_definition("memory") == MEMORY_BOT_CHANNEL_DEFINITION
    assert registry.get_channel("memory") is channel


def test_register_default_bot_channels_registers_memory_channel() -> None:
    registry = BotChannelRegistry()

    register_default_bot_channels(registry)

    assert registry.exists("memory")
    assert isinstance(registry.get_channel("memory"), InMemoryBotChannel)


def test_register_default_bot_channels_rejects_duplicate_registration() -> None:
    registry = BotChannelRegistry()
    register_default_bot_channels(registry)

    with pytest.raises(ConflictError):
        register_default_bot_channels(registry)
