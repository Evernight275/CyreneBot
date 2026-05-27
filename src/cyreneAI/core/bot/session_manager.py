from __future__ import annotations

from cyreneAI.core.bot.session_protocol import (
    BotSessionResolverProtocol,
    BotSessionStoreProtocol,
)
from cyreneAI.core.errors.bot import BotSessionNotFoundError
from cyreneAI.core.schema.bot import (
    BotConversationState,
    BotEvent,
    BotSession,
    BotSessionStatus,
    BotSessionUpdate,
)


class DefaultBotSessionResolver:
    """
    默认 bot session 解析器。
    """

    def resolve(self, event: BotEvent) -> BotSession:
        """
        直接使用标准化事件中的 session 信息。
        """
        return BotSession(
            session_id=event.session_id,
            channel_id=event.channel_id,
            user_id=event.user_id,
            thread_id=event.thread_id,
            metadata={
                "last_event_type": event.event_type,
            },
        )


class BotSessionManager:
    """
    bot session 生命周期管理器。
    """

    def __init__(
        self,
        store: BotSessionStoreProtocol,
        resolver: BotSessionResolverProtocol | None = None,
    ) -> None:
        self._store = store
        self._resolver = resolver or DefaultBotSessionResolver()

    async def get_or_create(self, event: BotEvent) -> BotConversationState:
        """
        获取或创建事件对应的会话状态。
        """
        try:
            return await self._store.get_state(event.session_id)
        except BotSessionNotFoundError:
            session = self._resolver.resolve(event)
            state = BotConversationState(session=session)
            await self._store.save_state(state)
            return state

    async def update_activity(
        self,
        *,
        session_id: str,
        event_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> BotConversationState:
        """
        记录会话活动。
        """
        return await self.update(
            BotSessionUpdate(
                session_id=session_id,
                last_event_id=event_id,
                increment_turn_count=True,
                metadata=metadata or {},
            )
        )

    async def update(self, update: BotSessionUpdate) -> BotConversationState:
        """
        更新会话状态。
        """
        state = await self._store.get_state(update.session_id)
        session = state.session
        if update.status is not None:
            session = session.model_copy(update={"status": update.status})

        metadata = {
            **state.metadata,
            **update.metadata,
        }
        state = state.model_copy(
            update={
                "session": session,
                "turn_count": (
                    state.turn_count + 1
                    if update.increment_turn_count
                    else state.turn_count
                ),
                "last_event_id": update.last_event_id or state.last_event_id,
                "metadata": metadata,
            }
        )
        await self._store.save_state(state)
        return state

    async def close(self, session_id: str) -> BotConversationState:
        """
        关闭会话。
        """
        return await self.update(
            BotSessionUpdate(
                session_id=session_id,
                status=BotSessionStatus.CLOSED,
            )
        )
