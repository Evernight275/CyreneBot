from __future__ import annotations

import asyncio

import pytest

from cyreneAI.core.errors.bot import BotSessionNotFoundError
from cyreneAI.core.schema.bot import BotConversationState, BotSession
from cyreneAI.infra.adapters.bot_sessions.memory import InMemoryBotSessionStore


def _state() -> BotConversationState:
    return BotConversationState(
        session=BotSession(
            session_id="memory:user-1",
            channel_id="memory",
            user_id="user-1",
        )
    )


def test_in_memory_bot_session_store_saves_and_deletes_state() -> None:
    async def run() -> None:
        store = InMemoryBotSessionStore()
        state = _state()

        await store.save_state(state)

        assert await store.get_state("memory:user-1") == state
        assert store.list_states() == [state]

        await store.delete_state("memory:user-1")
        assert store.list_states() == []
        with pytest.raises(BotSessionNotFoundError):
            await store.get_state("memory:user-1")

    asyncio.run(run())


def test_in_memory_bot_session_store_clears_state() -> None:
    async def run() -> None:
        store = InMemoryBotSessionStore()
        await store.save_state(_state())

        store.clear()

        assert store.list_states() == []

    asyncio.run(run())
