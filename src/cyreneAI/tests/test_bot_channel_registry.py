from __future__ import annotations

import pytest

from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.bot import BotChannelNotFoundError
from cyreneAI.core.schema.bot import BotAction, BotChannelDefinition


class FakeChannel:
    async def send(self, action: BotAction) -> None:
        pass


def _definition(channel_id: str = "memory") -> BotChannelDefinition:
    return BotChannelDefinition(
        channel_id=channel_id,
        name="Memory",
    )


def test_bot_channel_registry_registers_channel() -> None:
    registry = BotChannelRegistry()
    channel = FakeChannel()

    registry.register(_definition(), channel)

    assert registry.exists("memory")
    assert registry.get_definition("memory").name == "Memory"
    assert registry.get_channel("memory") is channel
    assert registry.list_definitions() == [_definition()]


def test_bot_channel_registry_rejects_duplicate_channel() -> None:
    registry = BotChannelRegistry()
    registry.register(_definition(), FakeChannel())

    with pytest.raises(ConflictError):
        registry.register(_definition(), FakeChannel())


def test_bot_channel_registry_unregisters_channel() -> None:
    registry = BotChannelRegistry()
    registry.register(_definition(), FakeChannel())

    registry.unregister("memory")

    assert not registry.exists("memory")
    with pytest.raises(BotChannelNotFoundError):
        registry.get_channel("memory")
