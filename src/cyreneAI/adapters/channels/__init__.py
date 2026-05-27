from __future__ import annotations

from cyreneAI.infra.adapters.channels.memory.channel import InMemoryBotChannel
from cyreneAI.infra.adapters.channels.telegram.channel import TelegramBotChannel


def create_memory_bot_channel() -> InMemoryBotChannel:
    """
    创建内存 bot channel。
    """
    return InMemoryBotChannel()


def create_telegram_bot_channel(
    *,
    token: str,
    channel_id: str = "telegram",
    base_url: str = "https://api.telegram.org",
    timeout: float = 30.0,
) -> TelegramBotChannel:
    """
    创建 Telegram bot channel。
    """
    return TelegramBotChannel(
        token=token,
        channel_id=channel_id,
        base_url=base_url,
        timeout=timeout,
    )


__all__ = [
    "InMemoryBotChannel",
    "TelegramBotChannel",
    "create_memory_bot_channel",
    "create_telegram_bot_channel",
]
