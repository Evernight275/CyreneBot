from __future__ import annotations

from cyreneAI.infra.adapters.vector_stores.memory.store import InMemoryVectorStore
from cyreneAI.infra.adapters.vector_stores.sqlite.builder import (
    create_sqlite_vector_engine,
    create_sqlite_vector_store,
)
from cyreneAI.infra.adapters.vector_stores.sqlite.store import SQLiteVectorStore


def create_memory_vector_store() -> InMemoryVectorStore:
    """
    创建内存向量存储。
    """
    return InMemoryVectorStore()


__all__ = [
    "InMemoryVectorStore",
    "SQLiteVectorStore",
    "create_memory_vector_store",
    "create_sqlite_vector_engine",
    "create_sqlite_vector_store",
]
