from __future__ import annotations

from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.infra.bootstrap.registrations.memory_bot_channel import (
    register_memory_bot_channel,
)


def register_default_bot_channels(
    registry: BotChannelRegistry,
) -> None:
    """
    注册默认 bot channel。
    """
    register_memory_bot_channel(registry)
