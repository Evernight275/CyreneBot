from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

from cyreneAI.core.bot.session_protocol import (
    BotSessionResolverProtocol,
    BotSessionStoreProtocol,
)
from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.bot import (
    BotInputError,
    BotSessionNotFoundError,
    BotStateError,
)
from cyreneAI.core.schema.bot import (
    BotConversationRef,
    BotConversationState,
    BotEvent,
    BotSession,
    BotSessionStatus,
    BotSessionUpdate,
)

DEFAULT_BOT_CONVERSATION_NAME = "default"


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
            state = await self._store.get_state(event.session_id)
        except BotSessionNotFoundError:
            session = self._resolver.resolve(event)
            state = _state_with_default_conversation(
                BotConversationState(session=session)
            )
            await self._store.save_state(state)
            return state
        state = _state_with_default_conversation(state)
        await self._store.save_state(state)
        return state

    async def get_state(self, session_id: str) -> BotConversationState:
        """
        获取已存在的会话状态。
        """
        state = await self._store.get_state(session_id)
        state = _state_with_default_conversation(state)
        await self._store.save_state(state)
        return state

    async def get_active_conversation(self, event: BotEvent) -> BotConversationRef:
        """
        获取事件对应 bot session 的当前活动对话。
        """
        state = await self.get_or_create(event)
        return _active_conversation(state)

    async def list_conversations(self, event: BotEvent) -> list[BotConversationRef]:
        """
        列出事件对应 bot session 下的全部对话。
        """
        state = await self.get_or_create(event)
        return list(state.conversations)

    async def get_conversation(
        self,
        event: BotEvent,
        name_or_id: str,
    ) -> BotConversationRef:
        """
        获取指定对话，不改变当前活动对话。
        """
        state = await self.get_or_create(event)
        return _find_conversation_or_raise(state, name_or_id)

    async def create_conversation(
        self,
        event: BotEvent,
        name: str,
    ) -> BotConversationRef:
        """
        创建新对话并设为当前活动对话。
        """
        state = await self.get_or_create(event)
        normalized_name = _normalize_conversation_name(name)
        if _find_conversation(state, normalized_name) is not None:
            raise ConflictError(f"Bot conversation already exists: {normalized_name}")

        conversation = _new_conversation(
            state.session.session_id,
            normalized_name,
        )
        state = state.model_copy(
            update={
                "active_conversation_id": conversation.conversation_id,
                "conversations": [
                    *state.conversations,
                    conversation,
                ],
            }
        )
        await self._store.save_state(state)
        return conversation

    async def use_conversation(
        self,
        event: BotEvent,
        name_or_id: str,
    ) -> BotConversationRef:
        """
        切换当前活动对话。
        """
        state = await self.get_or_create(event)
        conversation = _find_conversation_or_raise(state, name_or_id)
        state = state.model_copy(
            update={"active_conversation_id": conversation.conversation_id}
        )
        await self._store.save_state(state)
        return conversation

    async def rename_conversation(
        self,
        event: BotEvent,
        old_name_or_id: str,
        new_name: str,
    ) -> BotConversationRef:
        """
        重命名对话。为保留历史上下文，不改变 context_session_id。
        """
        state = await self.get_or_create(event)
        conversation = _find_conversation_or_raise(state, old_name_or_id)
        normalized_name = _normalize_conversation_name(new_name)
        existing = _find_conversation(state, normalized_name)
        if (
            existing is not None
            and existing.conversation_id != conversation.conversation_id
        ):
            raise ConflictError(f"Bot conversation already exists: {normalized_name}")

        renamed = conversation.model_copy(
            update={
                "name": normalized_name,
                "updated_at": datetime.now(UTC),
            }
        )
        conversations = [
            renamed if item.conversation_id == conversation.conversation_id else item
            for item in state.conversations
        ]
        state = state.model_copy(update={"conversations": conversations})
        await self._store.save_state(state)
        return renamed

    async def delete_conversation(
        self,
        event: BotEvent,
        name_or_id: str,
    ) -> BotConversationRef:
        """
        删除对话引用。至少保留一个对话。
        """
        state = await self.get_or_create(event)
        conversation = _find_conversation_or_raise(state, name_or_id)
        if len(state.conversations) <= 1:
            raise BotStateError("Cannot delete the last bot conversation")

        conversations = [
            item
            for item in state.conversations
            if item.conversation_id != conversation.conversation_id
        ]
        active_conversation_id = state.active_conversation_id
        if active_conversation_id == conversation.conversation_id:
            active_conversation_id = _preferred_active_conversation_id(conversations)
        state = state.model_copy(
            update={
                "active_conversation_id": active_conversation_id,
                "conversations": conversations,
            }
        )
        await self._store.save_state(state)
        return conversation

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
        state = _state_with_default_conversation(state)
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


def _state_with_default_conversation(
    state: BotConversationState,
) -> BotConversationState:
    conversations = list(state.conversations)
    if not conversations:
        default_conversation = _new_conversation(
            state.session.session_id,
            DEFAULT_BOT_CONVERSATION_NAME,
        )
        return state.model_copy(
            update={
                "active_conversation_id": default_conversation.conversation_id,
                "conversations": [default_conversation],
            }
        )

    active_conversation_id = state.active_conversation_id
    if active_conversation_id is None or not any(
        conversation.conversation_id == active_conversation_id
        for conversation in conversations
    ):
        active_conversation_id = _preferred_active_conversation_id(conversations)
    return state.model_copy(
        update={
            "active_conversation_id": active_conversation_id,
            "conversations": conversations,
        }
    )


def _preferred_active_conversation_id(
    conversations: list[BotConversationRef],
) -> str:
    default_id = _conversation_id_from_name(DEFAULT_BOT_CONVERSATION_NAME)
    for conversation in conversations:
        if conversation.conversation_id == default_id:
            return conversation.conversation_id
    return conversations[0].conversation_id


def _active_conversation(state: BotConversationState) -> BotConversationRef:
    for conversation in state.conversations:
        if conversation.conversation_id == state.active_conversation_id:
            return conversation
    if not state.conversations:
        raise BotStateError("Bot session has no conversations")
    return state.conversations[0]


def _new_conversation(
    session_id: str,
    name: str,
) -> BotConversationRef:
    normalized_name = _normalize_conversation_name(name)
    conversation_id = _conversation_id_from_name(normalized_name)
    return BotConversationRef(
        conversation_id=conversation_id,
        name=normalized_name,
        context_session_id=f"{session_id}:conversation:{conversation_id}",
    )


def _find_conversation(
    state: BotConversationState,
    name_or_id: str,
) -> BotConversationRef | None:
    normalized_name = _normalize_conversation_name(name_or_id)
    conversation_id = _conversation_id_from_name(normalized_name)
    for conversation in state.conversations:
        if conversation.conversation_id == conversation_id:
            return conversation
        if _normalize_conversation_name(conversation.name).casefold() == (
            normalized_name.casefold()
        ):
            return conversation
    return None


def _find_conversation_or_raise(
    state: BotConversationState,
    name_or_id: str,
) -> BotConversationRef:
    conversation = _find_conversation(state, name_or_id)
    if conversation is None:
        raise BotSessionNotFoundError(f"Bot conversation not found: {name_or_id}")
    return conversation


def _normalize_conversation_name(name: str) -> str:
    normalized = " ".join(name.strip().split())
    if not normalized:
        raise BotInputError("Bot conversation name cannot be empty")
    return normalized


def _conversation_id_from_name(name: str) -> str:
    return quote(_normalize_conversation_name(name).casefold(), safe="._-")
