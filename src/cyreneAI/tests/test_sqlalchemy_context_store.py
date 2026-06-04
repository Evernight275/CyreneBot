from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import SQLAlchemyError

from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.errors.context import (
    ContextInputError,
    ContextNotFoundError,
    ContextStoreError,
)
from cyreneAI.core.schema.context import ContextSnapshot, ContextWindow
from cyreneAI.infra.database.sqlalchemy.context_store import SQLAlchemyContextStore
from cyreneAI.infra.database.sqlalchemy.context_tables import (
    context_snapshots,
    create_context_tables,
)
from cyreneAI.infra.database.sqlite.builder import (
    create_sqlite_async_engine,
    create_sqlite_context_store,
)


def _snapshot(
    snapshot_id: str,
    session_id: str,
    *,
    value: str | None = None,
) -> ContextSnapshot:
    return ContextSnapshot(
        snapshot_id=snapshot_id,
        session_id=session_id,
        window=ContextWindow(
            window_id=f"{snapshot_id}:window",
            metadata={"value": value} if value is not None else {},
        ),
        metadata={"value": value} if value is not None else {},
    )


async def _run_store_lifecycle(database_path) -> None:
    store = await create_sqlite_context_store(database_path)
    try:
        first = _snapshot("snapshot-1", "session-1", value="first")
        second = _snapshot("snapshot-2", "session-1", value="second")
        other = _snapshot("snapshot-3", "session-2", value="other")

        await store.save_snapshot(first)
        await store.save_snapshot(second)
        await store.save_snapshot(other)

        assert await store.get_snapshot("snapshot-1") == first
        assert await store.list_snapshots("session-1") == [first, second]

        await store.delete_snapshot("snapshot-1")

        with pytest.raises(ContextNotFoundError):
            await store.get_snapshot("snapshot-1")
        assert await store.list_snapshots("session-1") == [second]

        assert await store.delete_snapshots_for_session("session-1") == 1
        assert await store.list_snapshots("session-1") == []
        assert await store.list_snapshots("session-2") == [other]
    finally:
        await store.close()


def test_sqlalchemy_context_store_persists_snapshot_lifecycle(tmp_path) -> None:
    asyncio.run(_run_store_lifecycle(tmp_path / "context.db"))


async def _run_store_overwrite(database_path) -> None:
    store = await create_sqlite_context_store(database_path)
    try:
        await store.save_snapshot(_snapshot("snapshot-1", "session-1", value="first"))
        latest = _snapshot("snapshot-1", "session-1", value="latest")
        await store.save_snapshot(latest)

        assert await store.get_snapshot("snapshot-1") == latest
        assert await store.list_snapshots("session-1") == [latest]
    finally:
        await store.close()


def test_sqlalchemy_context_store_overwrites_existing_snapshot(tmp_path) -> None:
    asyncio.run(_run_store_overwrite(tmp_path / "context.db"))


async def _run_context_manager_with_store(database_path) -> None:
    store = await create_sqlite_context_store(database_path)
    try:
        manager = ContextManager(store)
        snapshot = _snapshot("snapshot-1", "session-1", value="managed")

        await manager.save(snapshot)

        assert await manager.get("snapshot-1") == snapshot
        assert await manager.list_by_session("session-1") == [snapshot]

        await manager.remove("snapshot-1")

        with pytest.raises(ContextNotFoundError):
            await manager.get("snapshot-1")
    finally:
        await store.close()


def test_context_manager_works_with_sqlalchemy_context_store(tmp_path) -> None:
    asyncio.run(_run_context_manager_with_store(tmp_path / "context.db"))


class _FailingContext:
    async def __aenter__(self):
        raise SQLAlchemyError("database down")

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class _FailingEngine:
    def begin(self) -> _FailingContext:
        return _FailingContext()

    def connect(self) -> _FailingContext:
        return _FailingContext()

    async def dispose(self) -> None:
        return None


async def _run_store_translates_database_errors() -> None:
    store = SQLAlchemyContextStore(_FailingEngine())
    snapshot = _snapshot("snapshot-1", "session-1")

    with pytest.raises(ContextStoreError):
        await store.save_snapshot(snapshot)

    with pytest.raises(ContextStoreError):
        await store.get_snapshot("snapshot-1")

    with pytest.raises(ContextStoreError):
        await store.list_snapshots("session-1")

    with pytest.raises(ContextStoreError):
        await store.delete_snapshot("snapshot-1")

    with pytest.raises(ContextStoreError):
        await store.delete_snapshots_for_session("session-1")

    await store.close()


def test_sqlalchemy_context_store_translates_database_errors() -> None:
    asyncio.run(_run_store_translates_database_errors())


async def _run_store_rejects_invalid_payload(database_path) -> None:
    engine = create_sqlite_async_engine(database_path)
    await create_context_tables(engine)
    store = SQLAlchemyContextStore(engine)
    try:
        now = datetime.now(UTC)
        async with engine.begin() as connection:
            await connection.execute(
                insert(context_snapshots).values(
                    snapshot_id="snapshot-1",
                    session_id="session-1",
                    payload={"snapshot_id": "snapshot-1"},
                    created_at=now,
                    updated_at=now,
                )
            )

        with pytest.raises(ContextInputError):
            await store.get_snapshot("snapshot-1")
    finally:
        await store.close()


def test_sqlalchemy_context_store_rejects_invalid_payload(tmp_path) -> None:
    asyncio.run(_run_store_rejects_invalid_payload(tmp_path / "context.db"))
