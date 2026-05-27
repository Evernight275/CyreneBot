from __future__ import annotations

import asyncio

from cyreneAI.adapters.bot_sessions import (
    InMemoryBotSessionStore,
    create_memory_bot_session_store,
)
from cyreneAI.core.schema.bot import BotConversationState, BotSession


def test_create_memory_bot_session_store_returns_in_memory_store() -> None:
    store = create_memory_bot_session_store()

    assert isinstance(store, InMemoryBotSessionStore)


def test_create_memory_bot_session_store_returns_independent_instances() -> None:
    async def run() -> None:
        first = create_memory_bot_session_store()
        second = create_memory_bot_session_store()
        state = BotConversationState(
            session=BotSession(
                session_id="memory:user-1",
                channel_id="memory",
            )
        )

        await first.save_state(state)

        assert first is not second
        assert first.list_states() == [state]
        assert second.list_states() == []

    asyncio.run(run())
