from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert

from cyreneAI.core.errors.vector import (
    VectorInputError,
    VectorNotFoundError,
    VectorStoreError,
)
from cyreneAI.core.schema.vector import VectorQuery, VectorRecord
from cyreneAI.infra.adapters.vector_stores.sqlite.builder import (
    create_sqlite_vector_engine,
    create_sqlite_vector_store,
)
from cyreneAI.infra.adapters.vector_stores.sqlite.store import SQLiteVectorStore
from cyreneAI.infra.adapters.vector_stores.sqlite.tables import (
    create_vector_tables,
    vector_records,
)


async def _run_sqlite_vector_store_lifecycle(database_path) -> None:
    store = await create_sqlite_vector_store(database_path)
    try:
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

        latest = first.model_copy(update={"content": "alpha latest"})
        await store.upsert([latest])
        assert await store.get("record-1") == latest

        await store.delete("record-1")

        with pytest.raises(VectorNotFoundError):
            await store.get("record-1")
    finally:
        await store.close()


def test_sqlite_vector_store_lifecycle_and_search(tmp_path) -> None:
    asyncio.run(_run_sqlite_vector_store_lifecycle(tmp_path / "vectors.db"))


async def _run_sqlite_vector_store_persists_across_instances(database_path) -> None:
    first_store = await create_sqlite_vector_store(database_path)
    try:
        await first_store.upsert(
            [
                VectorRecord(
                    record_id="record-1",
                    vector=[1.0, 0.0],
                    content="alpha",
                )
            ]
        )
    finally:
        await first_store.close()

    second_store = await create_sqlite_vector_store(database_path)
    try:
        assert (await second_store.get("record-1")).content == "alpha"
    finally:
        await second_store.close()


def test_sqlite_vector_store_persists_across_instances(tmp_path) -> None:
    asyncio.run(
        _run_sqlite_vector_store_persists_across_instances(tmp_path / "vectors.db")
    )


async def _run_sqlite_vector_store_rejects_too_many_search_candidates(
    database_path,
) -> None:
    store = await create_sqlite_vector_store(database_path, max_search_candidates=1)
    try:
        await store.upsert(
            [
                VectorRecord(record_id="record-1", vector=[1.0, 0.0]),
                VectorRecord(record_id="record-2", vector=[0.0, 1.0]),
            ]
        )

        with pytest.raises(VectorStoreError):
            await store.search(VectorQuery(vector=[1.0, 0.0]))
    finally:
        await store.close()


def test_sqlite_vector_store_rejects_too_many_search_candidates(tmp_path) -> None:
    asyncio.run(
        _run_sqlite_vector_store_rejects_too_many_search_candidates(
            tmp_path / "vectors.db"
        )
    )


async def _run_sqlite_vector_store_rejects_invalid_vectors(database_path) -> None:
    store = await create_sqlite_vector_store(database_path)
    try:
        with pytest.raises(VectorInputError):
            await store.upsert([VectorRecord(record_id="zero", vector=[0.0, 0.0])])

        with pytest.raises(VectorInputError):
            await store.search(VectorQuery(vector=[0.0, 0.0]))

        with pytest.raises(VectorNotFoundError):
            await store.delete("missing")
    finally:
        await store.close()


def test_sqlite_vector_store_rejects_invalid_vectors(tmp_path) -> None:
    asyncio.run(_run_sqlite_vector_store_rejects_invalid_vectors(tmp_path / "vectors.db"))


async def _run_sqlite_vector_store_rejects_invalid_payload(database_path) -> None:
    engine = create_sqlite_vector_engine(database_path)
    await create_vector_tables(engine)
    store = SQLiteVectorStore(engine)
    try:
        now = datetime.now(UTC)
        async with engine.begin() as connection:
            await connection.execute(
                insert(vector_records).values(
                    record_id="record-1",
                    payload={"record_id": "record-1"},
                    created_at=now,
                    updated_at=now,
                )
            )

        with pytest.raises(VectorInputError):
            await store.get("record-1")
    finally:
        await store.close()


def test_sqlite_vector_store_rejects_invalid_payload(tmp_path) -> None:
    asyncio.run(_run_sqlite_vector_store_rejects_invalid_payload(tmp_path / "vectors.db"))
