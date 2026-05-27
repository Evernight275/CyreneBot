from __future__ import annotations

import asyncio

from cyreneAI.infra.database.sqlite.builder import (
    create_sqlite_async_engine,
    create_sqlite_context_store,
)


async def _run_sqlite_builder_initializes_tables(database_path) -> None:
    store = await create_sqlite_context_store(database_path)
    try:
        assert await store.list_snapshots("missing-session") == []
    finally:
        await store.close()


def test_sqlite_builder_initializes_context_tables(tmp_path) -> None:
    asyncio.run(_run_sqlite_builder_initializes_tables(tmp_path / "context.db"))


def test_create_sqlite_async_engine_uses_aiosqlite_driver(tmp_path) -> None:
    engine = create_sqlite_async_engine(tmp_path / "context.db")
    try:
        assert engine.url.drivername == "sqlite+aiosqlite"
    finally:
        asyncio.run(engine.dispose())
