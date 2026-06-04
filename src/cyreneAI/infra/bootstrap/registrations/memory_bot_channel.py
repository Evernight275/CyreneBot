from __future__ import annotations

from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.schema.bot import BotChannelDefinition
from cyreneAI.infra.adapters.channels.memory import InMemoryBotChannel

MEMORY_BOT_CHANNEL_DEFINITION = BotChannelDefinition(
    channel_id="memory",
    name="Memory Bot Channel",
    description="In-memory bot channel for tests and local development.",
)


def register_memory_bot_channel(
    registry: BotChannelRegistry,
    channel: InMemoryBotChannel | None = None,
) -> InMemoryBotChannel:
    """
    注册内存 bot channel。
    """
    runtime_channel = channel or InMemoryBotChannel()
    registry.register(MEMORY_BOT_CHANNEL_DEFINITION, runtime_channel)
    return runtime_channel
