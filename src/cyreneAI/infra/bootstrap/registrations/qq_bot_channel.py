from __future__ import annotations

from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.schema.bot import BotChannelDefinition
from cyreneAI.infra.adapters.channels.qq import QQBotChannel


QQ_BOT_CHANNEL_DEFINITION = BotChannelDefinition(
    channel_id="qq",
    name="QQ Bot Channel",
    description="QQ bot channel adapter.",
)


def register_qq_bot_channel(
    registry: BotChannelRegistry,
    *,
    token: str | None = None,
    app_id: str | None = None,
    app_secret: str | None = None,
    base_url: str = "https://api.sgroup.qq.com",
    token_url: str = "https://bots.qq.com/app/getAppAccessToken",
    channel: QQBotChannel | None = None,
) -> QQBotChannel:
    """
    Register the QQ bot channel.
    """
    runtime_channel = channel or QQBotChannel(
        token=token,
        app_id=app_id,
        app_secret=app_secret,
        base_url=base_url,
        token_url=token_url,
    )
    registry.register(QQ_BOT_CHANNEL_DEFINITION, runtime_channel)
    return runtime_channel
