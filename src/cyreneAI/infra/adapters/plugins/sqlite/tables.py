from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table
from sqlalchemy.ext.asyncio import AsyncEngine

metadata = MetaData()

plugin_task_instances = Table(
    "plugin_task_instances",
    metadata,
    Column("task_id", String, primary_key=True),
    Column("plugin_id", String, nullable=False, index=True),
    Column("task_name", String, nullable=False, index=True),
    Column("task_key", String, nullable=True, index=True),
    Column("payload", JSON, nullable=False),
    Column("run_at", DateTime(timezone=True), nullable=False, index=True),
    Column("status", String, nullable=False, index=True),
    Column("last_error", String, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


async def create_plugin_task_tables(engine: AsyncEngine) -> None:
    """
    创建插件受管任务实例表。
    """
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
