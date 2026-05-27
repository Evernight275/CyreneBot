from __future__ import annotations

import asyncio

from cyreneAI.adapters.vector_stores import (
    InMemoryVectorStore,
    create_memory_vector_store,
)
from cyreneAI.core.schema.vector import VectorQuery, VectorRecord


def test_create_memory_vector_store_returns_in_memory_store() -> None:
    store = create_memory_vector_store()

    assert isinstance(store, InMemoryVectorStore)


def test_create_memory_vector_store_returns_independent_instances() -> None:
    async def run() -> None:
        first = create_memory_vector_store()
        second = create_memory_vector_store()

        await first.upsert(
            [
                VectorRecord(
                    record_id="record-1",
                    vector=[1.0],
                    content="alpha",
                )
            ]
        )

        assert first is not second
        assert (await first.get("record-1")).content == "alpha"
        result = await second.search(VectorQuery(vector=[1.0]))
        assert result.matches == []

    asyncio.run(run())
