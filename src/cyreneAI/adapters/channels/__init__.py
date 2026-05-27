from __future__ import annotations

from cyreneAI.infra.adapters.channels.memory.channel import InMemoryBotChannel


def create_memory_bot_channel() -> InMemoryBotChannel:
    """
    创建内存 bot channel。
    """
    return InMemoryBotChannel()


__all__ = [
    "InMemoryBotChannel",
    "create_memory_bot_channel",
]
