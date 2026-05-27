from __future__ import annotations

from cyreneAI.core.bot.bot_protocol import BotChannelProtocol
from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.bot import BotChannelNotFoundError
from cyreneAI.core.schema.bot import BotChannelDefinition


class BotChannelRegistry:
    """
    bot channel 注册器。
    """

    def __init__(self) -> None:
        self._definitions: dict[str, BotChannelDefinition] = {}
        self._channels: dict[str, BotChannelProtocol] = {}

    def register(
        self,
        definition: BotChannelDefinition,
        channel: BotChannelProtocol,
    ) -> None:
        """
        注册 channel adapter。
        """
        if definition.channel_id in self._definitions:
            raise ConflictError(f"该 bot channel {definition.channel_id} 已注册")
        self._definitions[definition.channel_id] = definition
        self._channels[definition.channel_id] = channel

    def unregister(self, channel_id: str) -> None:
        """
        注销 channel adapter。
        """
        if channel_id not in self._definitions:
            raise BotChannelNotFoundError(f"该 bot channel {channel_id} 不存在")
        self._definitions.pop(channel_id, None)
        self._channels.pop(channel_id, None)

    def get_definition(self, channel_id: str) -> BotChannelDefinition:
        """
        获取 channel 定义。
        """
        definition = self._definitions.get(channel_id)
        if definition is None:
            raise BotChannelNotFoundError(f"该 bot channel {channel_id} 不存在")
        return definition

    def get_channel(self, channel_id: str) -> BotChannelProtocol:
        """
        获取 channel adapter。
        """
        channel = self._channels.get(channel_id)
        if channel is None:
            raise BotChannelNotFoundError(f"该 bot channel {channel_id} 不存在")
        return channel

    def exists(self, channel_id: str) -> bool:
        """
        判断 channel 是否存在。
        """
        return channel_id in self._definitions

    def list_definitions(self) -> list[BotChannelDefinition]:
        """
        列出 channel 定义。
        """
        return list(self._definitions.values())
