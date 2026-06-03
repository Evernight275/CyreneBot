from __future__ import annotations

import asyncio

import pytest

from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.bot import BotStateError
from cyreneAI.core.schema.bot import (
    BotEvent,
    BotEventType,
    BotSessionStatus,
    BotSessionUpdate,
)
from cyreneAI.infra.adapters.bot_sessions.memory import InMemoryBotSessionStore


def _event(event_id: str = "event-1") -> BotEvent:
    return BotEvent(
        event_id=event_id,
        event_type=BotEventType.MESSAGE,
        channel_id="memory",
        session_id="memory:user-1",
        user_id="user-1",
        thread_id="thread-1",
    )


def test_bot_session_manager_creates_and_updates_session_state() -> None:
    async def run() -> None:
        store = InMemoryBotSessionStore()
        manager = BotSessionManager(store)

        state = await manager.get_or_create(_event())
        assert state.session.session_id == "memory:user-1"
        assert state.session.channel_id == "memory"
        assert state.session.user_id == "user-1"
        assert state.session.thread_id == "thread-1"
        assert state.session.status == BotSessionStatus.ACTIVE
        assert state.turn_count == 0
        assert state.active_conversation_id == "default"
        assert len(state.conversations) == 1
        assert state.conversations[0].name == "default"
        assert (
            state.conversations[0].context_session_id
            == "memory:user-1:conversation:default"
        )

        updated = await manager.update_activity(
            session_id="memory:user-1",
            event_id="event-1",
            metadata={"source": "test"},
        )

        assert updated.turn_count == 1
        assert updated.last_event_id == "event-1"
        assert updated.metadata["source"] == "test"
        assert await store.get_state("memory:user-1") == updated

    asyncio.run(run())


def test_bot_session_manager_reuses_existing_session_state() -> None:
    async def run() -> None:
        manager = BotSessionManager(InMemoryBotSessionStore())

        first = await manager.get_or_create(_event("event-1"))
        await manager.update(
            BotSessionUpdate(
                session_id="memory:user-1",
                increment_turn_count=True,
            )
        )
        second = await manager.get_or_create(_event("event-2"))

        assert first.session == second.session
        assert second.turn_count == 1

    asyncio.run(run())


def test_bot_session_manager_closes_session() -> None:
    async def run() -> None:
        manager = BotSessionManager(InMemoryBotSessionStore())
        await manager.get_or_create(_event())

        state = await manager.close("memory:user-1")

        assert state.session.status == BotSessionStatus.CLOSED

    asyncio.run(run())


def test_bot_session_manager_manages_conversations() -> None:
    async def run() -> None:
        manager = BotSessionManager(InMemoryBotSessionStore())
        event = _event()

        created = await manager.create_conversation(event, "work")
        active = await manager.get_active_conversation(event)
        listed = await manager.list_conversations(event)

        assert created.name == "work"
        assert created.context_session_id == "memory:user-1:conversation:work"
        assert active == created
        assert [conversation.name for conversation in listed] == ["default", "work"]

        default = await manager.use_conversation(event, "default")

        assert default.name == "default"
        assert (await manager.get_active_conversation(event)).name == "default"

        renamed = await manager.rename_conversation(event, "work", "work notes")

        assert renamed.name == "work notes"
        assert renamed.conversation_id == "work"
        assert renamed.context_session_id == "memory:user-1:conversation:work"

        deleted = await manager.delete_conversation(event, "work notes")

        assert deleted.name == "work notes"
        assert [
            conversation.name
            for conversation in await manager.list_conversations(event)
        ] == ["default"]

    asyncio.run(run())


def test_bot_session_manager_rejects_duplicate_and_last_conversation_delete() -> None:
    async def run() -> None:
        manager = BotSessionManager(InMemoryBotSessionStore())
        event = _event()

        await manager.get_or_create(event)

        with pytest.raises(ConflictError):
            await manager.create_conversation(event, "default")

        with pytest.raises(BotStateError):
            await manager.delete_conversation(event, "default")

    asyncio.run(run())
