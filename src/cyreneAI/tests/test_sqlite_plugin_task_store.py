from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from cyreneAI.core.schema.plugin import PluginScheduledTask, PluginTaskStatus
from cyreneAI.infra.adapters.plugins.sqlite import create_sqlite_plugin_task_store


def _task(
    task_id: str = "task-1",
    *,
    key: str | None = "user-1",
    status: PluginTaskStatus = PluginTaskStatus.PENDING,
    run_at: datetime | None = None,
    lease_expires_at: datetime | None = None,
) -> PluginScheduledTask:
    now = datetime.now(UTC)
    return PluginScheduledTask(
        task_id=task_id,
        plugin_id="thirdparty.tasks",
        task_name="conversation_end",
        run_at=run_at or now + timedelta(seconds=60),
        payload={"user_id": "user-1"},
        key=key,
        status=status,
        lease_expires_at=lease_expires_at,
        created_at=now,
        updated_at=now,
    )


def test_sqlite_plugin_task_store_lifecycle(tmp_path) -> None:
    async def run() -> None:
        database_path = tmp_path / "plugin_tasks.db"
        store = await create_sqlite_plugin_task_store(database_path)
        await store.add_task(_task())

        pending_tasks = await store.list_pending_tasks(
            plugin_id="thirdparty.tasks",
            task_name="conversation_end",
        )
        assert len(pending_tasks) == 1
        assert pending_tasks[0].payload == {"user_id": "user-1"}
        assert (await store.get_task("task-1")).task_id == "task-1"

        await store.update_task_status("task-1", PluginTaskStatus.RUNNING)
        assert [task.task_id for task in await store.list_pending_tasks()] == ["task-1"]

        await store.update_task_status("task-1", PluginTaskStatus.COMPLETED)
        assert await store.list_pending_tasks() == []
        completed_tasks = await store.list_tasks(
            statuses=[PluginTaskStatus.COMPLETED],
        )
        assert [task.task_id for task in completed_tasks] == ["task-1"]
        await store.close()

        next_store = await create_sqlite_plugin_task_store(database_path)
        try:
            assert await next_store.list_pending_tasks() == []
        finally:
            await next_store.close()

    asyncio.run(run())


def test_sqlite_plugin_task_store_cancels_by_key(tmp_path) -> None:
    async def run() -> None:
        store = await create_sqlite_plugin_task_store(tmp_path / "plugin_tasks.db")
        try:
            await store.add_task(_task("task-1", key="same-key"))
            await store.add_task(_task("task-2", key="same-key"))

            cancelled_count = await store.cancel_task_key(
                "thirdparty.tasks",
                "same-key",
            )

            assert cancelled_count == 2
            assert await store.list_pending_tasks() == []
        finally:
            await store.close()

    asyncio.run(run())


def test_sqlite_plugin_task_store_claims_and_reschedules_with_lease(tmp_path) -> None:
    async def run() -> None:
        store = await create_sqlite_plugin_task_store(tmp_path / "plugin_tasks.db")
        try:
            now = datetime.now(UTC)
            await store.add_task(
                _task(
                    "task-1",
                    status=PluginTaskStatus.PENDING,
                ).model_copy(update={"max_attempts": 2})
            )

            claimed = await store.claim_task(
                "task-1",
                lease_owner="worker-1",
                lease_expires_at=now + timedelta(seconds=30),
            )
            assert claimed is True
            assert (await store.get_task("task-1")).lease_owner == "worker-1"

            second_claim = await store.claim_task(
                "task-1",
                lease_owner="worker-2",
                lease_expires_at=now + timedelta(seconds=30),
            )
            assert second_claim is False

            await store.heartbeat_task_lease(
                "task-1",
                lease_owner="worker-1",
                lease_expires_at=now + timedelta(seconds=60),
            )
            assert (await store.get_task("task-1")).lease_owner == "worker-1"

            await store.reschedule_task(
                "task-1",
                run_at=now + timedelta(seconds=5),
                attempt=1,
                last_error="boom",
            )
            task = await store.get_task("task-1")
            assert task.status == PluginTaskStatus.PENDING
            assert task.attempt == 1
            assert task.max_attempts == 2
            assert task.last_error == "boom"
            assert task.lease_owner is None
            assert task.lease_expires_at is None
        finally:
            await store.close()

    asyncio.run(run())


def test_sqlite_plugin_task_store_lists_runnable_tasks(tmp_path) -> None:
    async def run() -> None:
        store = await create_sqlite_plugin_task_store(tmp_path / "plugin_tasks.db")
        try:
            now = datetime.now(UTC)
            await store.add_task(
                _task(
                    "due-pending",
                    key=None,
                    run_at=now - timedelta(seconds=1),
                )
            )
            await store.add_task(
                _task(
                    "future-pending",
                    key=None,
                    run_at=now + timedelta(seconds=60),
                )
            )
            await store.add_task(
                _task(
                    "expired-running",
                    key=None,
                    status=PluginTaskStatus.RUNNING,
                    run_at=now - timedelta(seconds=10),
                    lease_expires_at=now - timedelta(seconds=1),
                )
            )
            await store.add_task(
                _task(
                    "leased-running",
                    key=None,
                    status=PluginTaskStatus.RUNNING,
                    run_at=now - timedelta(seconds=10),
                    lease_expires_at=now + timedelta(seconds=60),
                )
            )

            runnable = await store.list_runnable_tasks(now=now)

            assert [task.task_id for task in runnable] == [
                "expired-running",
                "due-pending",
            ]
        finally:
            await store.close()

    asyncio.run(run())
