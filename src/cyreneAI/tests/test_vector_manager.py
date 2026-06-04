from __future__ import annotations

import asyncio

from cyreneAI.core.schema.vector import (
    VectorQuery,
    VectorRecord,
    VectorSearchMatch,
    VectorSearchResult,
)
from cyreneAI.core.vector.manager import VectorManager


class FakeVectorStore:
    def __init__(self) -> None:
        self.records: dict[str, VectorRecord] = {}
        self.deleted_record_ids: list[str] = []
        self.closed = False

    async def upsert(self, records: list[VectorRecord]) -> None:
        for record in records:
            self.records[record.record_id] = record

    async def get(self, record_id: str) -> VectorRecord:
        return self.records[record_id]

    async def search(self, query: VectorQuery) -> VectorSearchResult:
        matches = [
            VectorSearchMatch(record=record, score=1.0)
            for record in self.records.values()
        ]
        return VectorSearchResult(matches=matches[: query.top_k])

    async def delete(self, record_id: str) -> None:
        self.deleted_record_ids.append(record_id)
        self.records.pop(record_id, None)

    async def close(self) -> None:
        self.closed = True


async def _run_vector_manager_lifecycle() -> None:
    store = FakeVectorStore()
    manager = VectorManager(store)
    first = VectorRecord(record_id="record-1", vector=[1.0, 0.0])
    second = VectorRecord(record_id="record-2", vector=[0.0, 1.0])

    await manager.upsert([first, second])

    assert await manager.get("record-1") == first
    assert [
        match.record
        for match in (await manager.search(VectorQuery(vector=[1.0, 0.0]))).matches
    ] == [
        first,
        second,
    ]

    await manager.delete("record-1")
    await manager.close()

    assert store.deleted_record_ids == ["record-1"]
    assert store.closed is True


def test_vector_manager_delegates_record_lifecycle_to_store() -> None:
    asyncio.run(_run_vector_manager_lifecycle())
