from __future__ import annotations

from sqlalchemy import JSON, DateTime, Index, MetaData, String, Table
from sqlalchemy import Column
from sqlalchemy.ext.asyncio import AsyncEngine

metadata = MetaData()

context_snapshots = Table(
    "context_snapshots",
    metadata,
    Column("snapshot_id", String(255), primary_key=True),
    Column("session_id", String(255), nullable=False, index=True),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Index(
        "ix_context_snapshots_session_updated_at",
        "session_id",
        "updated_at",
    ),
)


async def create_context_tables(engine: AsyncEngine) -> None:
    """
    创建上下文存储表
    """
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
