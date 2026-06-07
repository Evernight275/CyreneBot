from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from cyreneAI.core.errors.plugin import PluginNotFoundError
from cyreneAI.core.schema.plugin import PluginScheduledTask, PluginTaskStatus
from cyreneAI.infra.adapters.plugins.sqlite.tables import plugin_task_instances


class SQLitePluginTaskStore:
    """
    SQLite 插件受管任务实例存储。
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def add_task(self, task: PluginScheduledTask) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                insert(plugin_task_instances).values(
                    task_id=task.task_id,
                    plugin_id=task.plugin_id,
                    task_name=task.task_name,
                    task_key=task.key,
                    payload=task.payload,
                    run_at=task.run_at,
                    attempt=task.attempt,
                    max_attempts=task.max_attempts,
                    status=task.status.value,
                    last_error=task.last_error,
                    lease_owner=task.lease_owner,
                    lease_expires_at=task.lease_expires_at,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
            )

    async def list_pending_tasks(
        self,
        *,
        plugin_id: str | None = None,
        task_name: str | None = None,
    ) -> list[PluginScheduledTask]:
        return await self.list_tasks(
            plugin_id=plugin_id,
            task_name=task_name,
            statuses=[
                PluginTaskStatus.PENDING,
                PluginTaskStatus.RUNNING,
            ],
        )

    async def list_tasks(
        self,
        *,
        plugin_id: str | None = None,
        task_name: str | None = None,
        statuses: list[PluginTaskStatus] | None = None,
    ) -> list[PluginScheduledTask]:
        statement = select(plugin_task_instances)
        if statuses is not None:
            statement = statement.where(
                plugin_task_instances.c.status.in_(
                    [status.value for status in statuses]
                )
            )
        if plugin_id is not None:
            statement = statement.where(plugin_task_instances.c.plugin_id == plugin_id)
        if task_name is not None:
            statement = statement.where(plugin_task_instances.c.task_name == task_name)
        statement = statement.order_by(plugin_task_instances.c.run_at)

        async with self._engine.connect() as connection:
            result = await connection.execute(statement)
            rows = result.mappings().all()
        return [_task_from_row(dict(row)) for row in rows]

    async def get_task(self, task_id: str) -> PluginScheduledTask:
        statement = select(plugin_task_instances).where(
            plugin_task_instances.c.task_id == task_id
        )
        async with self._engine.connect() as connection:
            result = await connection.execute(statement)
            row = result.mappings().one_or_none()
        if row is None:
            raise PluginNotFoundError(f"插件任务实例 {task_id} 不存在")
        return _task_from_row(dict(row))

    async def update_task_status(
        self,
        task_id: str,
        status: PluginTaskStatus,
        *,
        last_error: str | None = None,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                update(plugin_task_instances)
                .where(plugin_task_instances.c.task_id == task_id)
                .values(
                    status=status.value,
                    last_error=last_error,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=datetime.now(UTC),
                )
            )

    async def claim_task(
        self,
        task_id: str,
        *,
        lease_owner: str,
        lease_expires_at: datetime,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(plugin_task_instances)
                .where(
                    plugin_task_instances.c.task_id == task_id,
                    plugin_task_instances.c.status.in_(
                        [
                            PluginTaskStatus.PENDING.value,
                            PluginTaskStatus.RUNNING.value,
                        ]
                    ),
                    or_(
                        plugin_task_instances.c.lease_owner.is_(None),
                        plugin_task_instances.c.lease_owner == lease_owner,
                        plugin_task_instances.c.lease_expires_at.is_(None),
                        plugin_task_instances.c.lease_expires_at <= now,
                    ),
                )
                .values(
                    status=PluginTaskStatus.RUNNING.value,
                    lease_owner=lease_owner,
                    lease_expires_at=lease_expires_at,
                    updated_at=now,
                )
            )
            return bool(result.rowcount)

    async def heartbeat_task_lease(
        self,
        task_id: str,
        *,
        lease_owner: str,
        lease_expires_at: datetime,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                update(plugin_task_instances)
                .where(
                    plugin_task_instances.c.task_id == task_id,
                    plugin_task_instances.c.status == PluginTaskStatus.RUNNING.value,
                    plugin_task_instances.c.lease_owner == lease_owner,
                )
                .values(
                    lease_expires_at=lease_expires_at,
                    updated_at=datetime.now(UTC),
                )
            )

    async def reschedule_task(
        self,
        task_id: str,
        *,
        run_at: datetime,
        attempt: int,
        last_error: str | None = None,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                update(plugin_task_instances)
                .where(
                    plugin_task_instances.c.task_id == task_id,
                    plugin_task_instances.c.status.in_(
                        [
                            PluginTaskStatus.PENDING.value,
                            PluginTaskStatus.RUNNING.value,
                            PluginTaskStatus.FAILED.value,
                        ]
                    ),
                )
                .values(
                    run_at=run_at,
                    attempt=attempt,
                    status=PluginTaskStatus.PENDING.value,
                    last_error=last_error,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=datetime.now(UTC),
                )
            )

    async def cancel_task(self, task_id: str) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                update(plugin_task_instances)
                .where(
                    plugin_task_instances.c.task_id == task_id,
                    plugin_task_instances.c.status.in_(
                        [
                            PluginTaskStatus.PENDING.value,
                            PluginTaskStatus.RUNNING.value,
                        ]
                    ),
                )
                .values(
                    status=PluginTaskStatus.CANCELED.value,
                    last_error=None,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=datetime.now(UTC),
                )
            )

    async def cancel_task_key(self, plugin_id: str, key: str) -> int:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(plugin_task_instances)
                .where(
                    plugin_task_instances.c.plugin_id == plugin_id,
                    plugin_task_instances.c.task_key == key,
                    plugin_task_instances.c.status.in_(
                        [
                            PluginTaskStatus.PENDING.value,
                            PluginTaskStatus.RUNNING.value,
                        ]
                    ),
                )
                .values(
                    status=PluginTaskStatus.CANCELED.value,
                    last_error=None,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=datetime.now(UTC),
                )
            )
            return int(result.rowcount or 0)

    async def close(self) -> None:
        await self._engine.dispose()


def _task_from_row(row: dict[str, Any]) -> PluginScheduledTask:
    return PluginScheduledTask(
        task_id=str(row["task_id"]),
        plugin_id=str(row["plugin_id"]),
        task_name=str(row["task_name"]),
        key=str(row["task_key"]) if row["task_key"] is not None else None,
        payload=dict(row["payload"] or {}),
        run_at=_ensure_utc(row["run_at"]),
        attempt=int(row.get("attempt") or 0),
        max_attempts=int(row.get("max_attempts") or 1),
        status=PluginTaskStatus(str(row["status"])),
        last_error=(str(row["last_error"]) if row["last_error"] is not None else None),
        lease_owner=(
            str(row["lease_owner"]) if row.get("lease_owner") is not None else None
        ),
        lease_expires_at=(
            _ensure_utc(row["lease_expires_at"])
            if row.get("lease_expires_at") is not None
            else None
        ),
        created_at=_ensure_utc(row["created_at"]),
        updated_at=_ensure_utc(row["updated_at"]),
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
