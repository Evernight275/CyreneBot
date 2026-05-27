from __future__ import annotations

from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.schema.bot import BotChannelDefinition
from cyreneAI.infra.adapters.channels.telegram import TelegramBotChannel


TELEGRAM_BOT_CHANNEL_DEFINITION = BotChannelDefinition(
    channel_id="telegram",
    name="Telegram Bot Channel",
    description="Telegram Bot API channel adapter.",
)


def register_telegram_bot_channel(
    registry: BotChannelRegistry,
    *,
    token: str | None = None,
    channel: TelegramBotChannel | None = None,
) -> TelegramBotChannel:
    """
    注册 Telegram bot channel。
    """
    runtime_channel = channel or TelegramBotChannel(token=token)
    registry.register(TELEGRAM_BOT_CHANNEL_DEFINITION, runtime_channel)
    return runtime_channel
