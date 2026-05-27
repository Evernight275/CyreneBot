from __future__ import annotations

from typing import Any, Protocol

from cyreneAI.core.schema.bot import BotAction, BotChannelDefinition, BotEvent


class BotChannelProtocol(Protocol):
    """
    channel adapter 协议。
    """

    async def send(self, action: BotAction) -> None:
        """
        把标准化 bot 动作发送到外部 channel。
        """
        ...


class BotEventHandlerProtocol(Protocol):
    """
    bot 事件处理协议。
    """

    async def handle(self, event: BotEvent) -> list[BotAction]:
        """
        处理标准化 bot 事件并返回 channel 动作。
        """
        ...


class BotUpdateMapperProtocol(Protocol):
    """
    channel update 映射协议。
    """

    def map_update(self, update: dict[str, Any]) -> BotEvent:
        """
        将外部 channel update 映射为标准 BotEvent。
        """
        ...


class BotChannelRegistryProtocol(Protocol):
    """
    bot channel 注册器协议。
    """

    def get_definition(self, channel_id: str) -> BotChannelDefinition:
        """
        获取 channel 定义。
        """
        ...

    def get_channel(self, channel_id: str) -> BotChannelProtocol:
        """
        获取 channel adapter。
        """
        ...

    def exists(self, channel_id: str) -> bool:
        """
        判断 channel 是否存在。
        """
        ...

    def list_definitions(self) -> list[BotChannelDefinition]:
        """
        列出 channel 定义。
        """
        ...
