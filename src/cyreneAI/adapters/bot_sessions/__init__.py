from __future__ import annotations

from cyreneAI.infra.adapters.bot_sessions.memory.store import InMemoryBotSessionStore


def create_memory_bot_session_store() -> InMemoryBotSessionStore:
    """
    创建内存 bot session store。
    """
    return InMemoryBotSessionStore()


__all__ = [
    "InMemoryBotSessionStore",
    "create_memory_bot_session_store",
]
