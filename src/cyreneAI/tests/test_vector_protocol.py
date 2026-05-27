from __future__ import annotations

import asyncio
from pathlib import Path

from cyreneAI.core.schema.vector import (
    VectorQuery,
    VectorRecord,
    VectorSearchMatch,
    VectorSearchResult,
)
from cyreneAI.core.vector.vector_protocol import VectorStoreProtocol


class FakeVectorStore:
    def __init__(self) -> None:
        self.records: dict[str, VectorRecord] = {}

    async def upsert(self, records: list[VectorRecord]) -> None:
        for record in records:
            self.records[record.record_id] = record

    async def get(self, record_id: str) -> VectorRecord:
        return self.records[record_id]

    async def search(self, query: VectorQuery) -> VectorSearchResult:
        return VectorSearchResult(
            matches=[
                VectorSearchMatch(
                    record=record,
                    score=1.0,
                )
                for record in self.records.values()
            ][: query.top_k]
        )

    async def delete(self, record_id: str) -> None:
        self.records.pop(record_id, None)


async def _use_vector_store(store: VectorStoreProtocol) -> None:
    record = VectorRecord(
        record_id="record-1",
        vector=[1.0, 0.0],
        content="hello",
    )

    await store.upsert([record])

    assert await store.get("record-1") == record
    assert (await store.search(VectorQuery(vector=[1.0, 0.0]))).matches[0].record == record

    await store.delete("record-1")
    assert store.records == {}


def test_vector_store_protocol_can_be_implemented_by_fake() -> None:
    asyncio.run(_use_vector_store(FakeVectorStore()))


def test_core_vector_does_not_import_infra_or_external_sdks() -> None:
    vector_dir = Path(__file__).parents[1] / "core" / "vector"
    forbidden_patterns = [
        "cyreneAI.infra",
        "openai",
        "anthropic",
        "google.genai",
        "httpx",
        "dotenv",
        "os.getenv",
    ]

    for path in vector_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            assert pattern not in text
