from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table, text
from sqlalchemy.exc import OperationalError
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
    Column("attempt", Integer, nullable=False, default=0),
    Column("max_attempts", Integer, nullable=False, default=1),
    Column("status", String, nullable=False, index=True),
    Column("last_error", String, nullable=True),
    Column("lease_owner", String, nullable=True, index=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=True, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


async def create_plugin_task_tables(engine: AsyncEngine) -> None:
    """
    创建插件受管任务实例表。
    """
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await _add_column_if_missing(
            connection,
            "ALTER TABLE plugin_task_instances "
            "ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0",
        )
        await _add_column_if_missing(
            connection,
            "ALTER TABLE plugin_task_instances "
            "ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 1",
        )
        await _add_column_if_missing(
            connection,
            "ALTER TABLE plugin_task_instances ADD COLUMN lease_owner VARCHAR",
        )
        await _add_column_if_missing(
            connection,
            "ALTER TABLE plugin_task_instances ADD COLUMN lease_expires_at DATETIME",
        )


async def _add_column_if_missing(connection, statement: str) -> None:
    try:
        await connection.execute(text(statement))
    except OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise
