from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from cyreneAI.infra.adapters.vector_stores.sqlite.store import SQLiteVectorStore
from cyreneAI.infra.adapters.vector_stores.sqlite.tables import create_vector_tables


def create_sqlite_vector_engine(
    path: str | Path,
    *,
    echo: bool = False,
) -> AsyncEngine:
    """
    创建 SQLite 向量存储 AsyncEngine。
    """
    return create_async_engine(
        _build_sqlite_url(path),
        echo=echo,
    )


async def create_sqlite_vector_store(
    path: str | Path,
    *,
    echo: bool = False,
    max_search_candidates: int = 10_000,
) -> SQLiteVectorStore:
    """
    创建 SQLite 向量存储。
    """
    engine = create_sqlite_vector_engine(path, echo=echo)
    await create_vector_tables(engine)
    return SQLiteVectorStore(
        engine,
        max_search_candidates=max_search_candidates,
    )


def _build_sqlite_url(path: str | Path) -> str:
    if str(path) == ":memory:":
        return "sqlite+aiosqlite:///:memory:"

    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{database_path.as_posix()}"
