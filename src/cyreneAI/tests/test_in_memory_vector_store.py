from __future__ import annotations

import asyncio

import pytest

from cyreneAI.core.errors.vector import VectorInputError, VectorNotFoundError
from cyreneAI.core.schema.vector import VectorQuery, VectorRecord
from cyreneAI.infra.adapters.vector_stores.memory.store import InMemoryVectorStore


async def _run_memory_vector_store_lifecycle() -> None:
    store = InMemoryVectorStore()
    first = VectorRecord(
        record_id="record-1",
        vector=[1.0, 0.0],
        content="alpha",
        metadata={"kind": "doc"},
    )
    second = VectorRecord(
        record_id="record-2",
        vector=[0.0, 1.0],
        content="beta",
        metadata={"kind": "doc"},
    )
    third = VectorRecord(
        record_id="record-3",
        vector=[1.0, 1.0],
        content="gamma",
        metadata={"kind": "note"},
    )

    await store.upsert([first, second, third])

    assert await store.get("record-1") == first

    result = await store.search(
        VectorQuery(
            vector=[1.0, 0.0],
            top_k=2,
            filters={"kind": "doc"},
            metadata={"purpose": "test"},
        )
    )

    assert [match.record.record_id for match in result.matches] == [
        "record-1",
        "record-2",
    ]
    assert result.matches[0].score > result.matches[1].score
    assert result.metadata == {
        "purpose": "test",
        "candidate_count": 3,
    }

    await store.delete("record-1")

    with pytest.raises(VectorNotFoundError):
        await store.get("record-1")

    await store.close()


def test_in_memory_vector_store_lifecycle_and_search() -> None:
    asyncio.run(_run_memory_vector_store_lifecycle())


async def _run_memory_vector_store_rejects_invalid_vectors() -> None:
    store = InMemoryVectorStore()

    with pytest.raises(VectorInputError):
        await store.upsert([VectorRecord(record_id="zero", vector=[0.0, 0.0])])

    with pytest.raises(VectorInputError):
        await store.search(VectorQuery(vector=[0.0, 0.0]))

    with pytest.raises(VectorNotFoundError):
        await store.delete("missing")


def test_in_memory_vector_store_rejects_invalid_vectors() -> None:
    asyncio.run(_run_memory_vector_store_rejects_invalid_vectors())
