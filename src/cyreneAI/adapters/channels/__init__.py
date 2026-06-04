from __future__ import annotations

from cyreneAI.infra.adapters.channels.memory.channel import InMemoryBotChannel
from cyreneAI.infra.adapters.channels.qq.channel import QQBotChannel
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


def create_qq_bot_channel(
    *,
    token: str | None = None,
    app_id: str | None = None,
    app_secret: str | None = None,
    channel_id: str = "qq",
    base_url: str = "https://api.sgroup.qq.com",
    token_url: str = "https://bots.qq.com/app/getAppAccessToken",
    timeout: float = 30.0,
) -> QQBotChannel:
    """
    创建 QQ bot channel。
    """
    return QQBotChannel(
        token=token,
        app_id=app_id,
        app_secret=app_secret,
        channel_id=channel_id,
        base_url=base_url,
        token_url=token_url,
        timeout=timeout,
    )


__all__ = [
    "InMemoryBotChannel",
    "QQBotChannel",
    "TelegramBotChannel",
    "create_memory_bot_channel",
    "create_qq_bot_channel",
    "create_telegram_bot_channel",
]
