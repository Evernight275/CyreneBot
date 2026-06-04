from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table
from sqlalchemy.ext.asyncio import AsyncEngine

metadata = MetaData()

vector_records = Table(
    "vector_records",
    metadata,
    Column("record_id", String, primary_key=True),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


async def create_vector_tables(engine: AsyncEngine) -> None:
    """
    创建向量存储表。
    """
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
