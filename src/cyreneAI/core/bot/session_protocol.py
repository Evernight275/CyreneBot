from __future__ import annotations

from typing import Protocol

from cyreneAI.core.schema.bot import (
    BotConversationState,
    BotEvent,
    BotSession,
)


class BotSessionStoreProtocol(Protocol):
    """
    bot session 存储协议。
    """

    async def get_state(self, session_id: str) -> BotConversationState:
        """
        获取会话状态。
        """
        ...

    async def save_state(self, state: BotConversationState) -> None:
        """
        保存会话状态。
        """
        ...

    async def delete_state(self, session_id: str) -> None:
        """
        删除会话状态。
        """
        ...


class BotSessionResolverProtocol(Protocol):
    """
    bot session 解析协议。
    """

    def resolve(self, event: BotEvent) -> BotSession:
        """
        从标准化事件解析 session 引用。
        """
        ...
