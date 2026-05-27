from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from cyreneAI.infra.database.sqlalchemy.context_store import SQLAlchemyContextStore
from cyreneAI.infra.database.sqlalchemy.context_tables import create_context_tables


def create_sqlite_async_engine(
    path: str | Path,
    *,
    echo: bool = False,
) -> AsyncEngine:
    """
    创建 SQLite AsyncEngine
    """
    return create_async_engine(
        _build_sqlite_url(path),
        echo=echo,
    )


async def create_sqlite_context_store(
    path: str | Path,
    *,
    echo: bool = False,
) -> SQLAlchemyContextStore:
    """
    创建 SQLite 上下文存储
    """
    engine = create_sqlite_async_engine(path, echo=echo)
    await create_context_tables(engine)
    return SQLAlchemyContextStore(engine)


def _build_sqlite_url(path: str | Path) -> str:
    if str(path) == ":memory:":
        return "sqlite+aiosqlite:///:memory:"

    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{database_path.as_posix()}"
