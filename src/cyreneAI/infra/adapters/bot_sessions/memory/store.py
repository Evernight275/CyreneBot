from __future__ import annotations

from cyreneAI.core.errors.bot import BotSessionNotFoundError
from cyreneAI.core.schema.bot import BotConversationState


class InMemoryBotSessionStore:
    """
    内存 bot session store，适合测试和本地开发。
    """

    def __init__(self) -> None:
        self._states: dict[str, BotConversationState] = {}

    async def get_state(self, session_id: str) -> BotConversationState:
        """
        获取会话状态。
        """
        state = self._states.get(session_id)
        if state is None:
            raise BotSessionNotFoundError(f"Bot session not found: {session_id}")
        return state

    async def save_state(self, state: BotConversationState) -> None:
        """
        保存会话状态。
        """
        self._states[state.session.session_id] = state

    async def delete_state(self, session_id: str) -> None:
        """
        删除会话状态。
        """
        if session_id not in self._states:
            raise BotSessionNotFoundError(f"Bot session not found: {session_id}")
        self._states.pop(session_id, None)

    def list_states(self) -> list[BotConversationState]:
        """
        列出当前状态。
        """
        return list(self._states.values())

    def clear(self) -> None:
        """
        清空全部状态。
        """
        self._states.clear()
