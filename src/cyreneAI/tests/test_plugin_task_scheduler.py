from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from cyreneAI.api import CyreneBot, Depends
from cyreneAI.application.plugins.tasks import ApplicationPluginTaskScheduler
from cyreneAI.bootstrap import build_cyrene_ai_runtime
from cyreneAI.core.errors.plugin import (
    PluginConfigurationError,
    PluginNotFoundError,
    PluginStateError,
)
from cyreneAI.core.schema.bot import BotCommand
from cyreneAI.core.schema.plugin import (
    PluginCapability,
    PluginCommandRequest,
    PluginCommandResult,
    PluginManifest,
    PluginPermission,
    PluginScheduledTask,
    PluginTaskDefinition,
    PluginTaskResult,
    PluginTaskStatus,
)
from cyreneAI.infra.adapters.plugins.sqlite import create_sqlite_plugin_task_store


class _FakePluginLoader:
    def __init__(self, *modules: object) -> None:
        self._modules = list(modules)

    def load(self) -> list[object]:
        return self._modules


class _RecordingTaskExecutor:
    def __init__(self, called: asyncio.Event) -> None:
        self.called = called
        self.payloads: list[dict[str, object]] = []

    async def execute(self, request) -> PluginTaskResult:
        self.payloads.append(dict(request.payload))
        self.called.set()
        return PluginTaskResult()


class _FakeTaskStore:
    def __init__(self) -> None:
        self.closed = False
        self.cancelled_task_ids: list[str] = []
        self.cancelled_keys: list[tuple[str, str]] = []
        self.runnable_error: Exception | None = None
        self.pending_error: Exception | None = None
        now = datetime.now(UTC)
        self.task = PluginScheduledTask(
            task_id="failed-task",
            plugin_id="thirdparty.tasks",
            task_name="conversation_end",
            run_at=now,
            status=PluginTaskStatus.FAILED,
            created_at=now,
            updated_at=now,
        )

    async def close(self) -> None:
        self.closed = True

    async def list_tasks(self, **kwargs) -> list[PluginScheduledTask]:
        return [self.task]

    async def get_task(self, task_id: str) -> PluginScheduledTask:
        return self.task

    async def cancel_task(self, task_id: str) -> None:
        self.cancelled_task_ids.append(task_id)

    async def cancel_task_key(self, plugin_id: str, key: str) -> int:
        self.cancelled_keys.append((plugin_id, key))
        return 3

    async def list_runnable_tasks(self, **kwargs) -> list[PluginScheduledTask]:
        if self.runnable_error is not None:
            raise self.runnable_error
        return []

    async def list_pending_tasks(
        self,
        *,
        plugin_id: str,
        task_name: str,
    ) -> list[PluginScheduledTask]:
        if self.pending_error is not None:
            raise self.pending_error
        return []


def test_plugin_task_scheduler_rejects_invalid_scheduler_config() -> None:
    with pytest.raises(PluginConfigurationError, match="max_concurrent_tasks"):
        ApplicationPluginTaskScheduler(max_concurrent_tasks=0)

    with pytest.raises(PluginConfigurationError, match="lease_seconds"):
        ApplicationPluginTaskScheduler(lease_seconds=0)

    with pytest.raises(PluginConfigurationError, match="scan_interval_seconds"):
        ApplicationPluginTaskScheduler(scan_interval_seconds=0)


def test_plugin_task_scheduler_rejects_invalid_task_definitions() -> None:
    scheduler = ApplicationPluginTaskScheduler()
    executor = _RecordingTaskExecutor(asyncio.Event())

    with pytest.raises(PluginConfigurationError, match="name"):
        scheduler.register_task("thirdparty.tasks", PluginTaskDefinition(name=" / "), executor)

    with pytest.raises(PluginConfigurationError, match="interval_seconds"):
        scheduler.register_task(
            "thirdparty.tasks",
            PluginTaskDefinition(name="bad_interval", interval_seconds=0),
            executor,
        )

    with pytest.raises(PluginConfigurationError, match="不能同时声明"):
        scheduler.register_task(
            "thirdparty.tasks",
            PluginTaskDefinition(
                name="bad_schedule",
                interval_seconds=1,
                daily_at="09:30",
            ),
            executor,
        )

    with pytest.raises(PluginConfigurationError, match="HH:MM"):
        scheduler.register_task(
            "thirdparty.tasks",
            PluginTaskDefinition(name="bad_daily", daily_at="morning"),
            executor,
        )

    scheduler.register_task(
        "thirdparty.tasks",
        PluginTaskDefinition(name=" /Conversation   End "),
        executor,
    )
    with pytest.raises(PluginConfigurationError, match="重复注册"):
        scheduler.register_task(
            "thirdparty.tasks",
            PluginTaskDefinition(name="conversation end"),
            executor,
        )


def test_plugin_task_scheduler_in_memory_error_paths() -> None:
    async def run() -> None:
        scheduler = ApplicationPluginTaskScheduler()

        assert await scheduler.list_tasks() == []
        assert await scheduler.cancel_key("thirdparty.tasks", "  ") == 0
        assert await scheduler.cancel_key("thirdparty.tasks", "missing") == 0

        with pytest.raises(PluginStateError, match="plugin task store"):
            await scheduler.retry_task("missing")

        with pytest.raises(PluginConfigurationError, match="delay_seconds"):
            await scheduler.schedule_once(
                "thirdparty.tasks",
                "conversation_end",
                delay_seconds=-1,
            )

        with pytest.raises(PluginNotFoundError):
            await scheduler.schedule_once(
                "thirdparty.tasks",
                "missing",
                delay_seconds=0,
            )

    asyncio.run(run())


def test_plugin_task_scheduler_namespace_schedules_and_cancels_key() -> None:
    async def run() -> None:
        scheduler = ApplicationPluginTaskScheduler()
        scheduler.register_task(
            "thirdparty.tasks",
            PluginTaskDefinition(name="conversation_end"),
            _RecordingTaskExecutor(asyncio.Event()),
        )
        namespace = scheduler.namespace("thirdparty.tasks")

        task_id = await namespace.schedule_once(
            "conversation_end",
            delay_seconds=60,
            key="user-1",
        )
        cancelled = await namespace.cancel_key("user-1")

        assert task_id.startswith("thirdparty.tasks:conversation_end:")
        assert cancelled == 1
        assert scheduler._managed_tasks == {}
        assert scheduler._task_keys == {}

    asyncio.run(run())


def test_plugin_task_scheduler_cancel_delegates_to_store_and_cancels_task() -> None:
    async def run() -> None:
        store = _FakeTaskStore()
        scheduler = ApplicationPluginTaskScheduler(store=store)
        task = asyncio.create_task(asyncio.sleep(60))
        scheduler._track_managed_task("task-1", task)
        scheduler._task_keys[("thirdparty.tasks", "user-1")] = "task-1"

        await scheduler.cancel("task-1")
        await scheduler.cancel("missing-task")

        assert store.cancelled_task_ids == ["task-1", "missing-task"]
        assert ("thirdparty.tasks", "user-1") not in scheduler._task_keys
        assert scheduler._managed_tasks == {}

    asyncio.run(run())


def test_plugin_task_scheduler_cancel_key_delegates_to_store() -> None:
    async def run() -> None:
        store = _FakeTaskStore()
        scheduler = ApplicationPluginTaskScheduler(store=store)

        cancelled = await scheduler.cancel_key("thirdparty.tasks", " user-1 ")

        assert cancelled == 3
        assert store.cancelled_keys == [("thirdparty.tasks", "user-1")]

    asyncio.run(run())


def test_plugin_task_scheduler_shutdown_cancels_tasks_and_closes_store() -> None:
    async def run() -> None:
        store = _FakeTaskStore()
        scheduler = ApplicationPluginTaskScheduler(store=store)
        task = asyncio.create_task(asyncio.sleep(60))
        scheduler._track_managed_task("task-1", task)

        await scheduler.shutdown()
        await scheduler.shutdown()

        assert store.closed is True
        assert scheduler._managed_tasks == {}

    asyncio.run(run())


def test_plugin_task_scheduler_logs_scan_and_restore_errors(caplog) -> None:
    async def run() -> None:
        store = _FakeTaskStore()
        store.runnable_error = RuntimeError("scan failed")
        store.pending_error = RuntimeError("restore failed")
        scheduler = ApplicationPluginTaskScheduler(store=store)

        await scheduler._scan_runnable_tasks()
        await scheduler._restore_pending_tasks(
            "thirdparty.tasks",
            "conversation_end",
        )

    with caplog.at_level("ERROR", logger="cyreneAI.application.plugins.tasks"):
        asyncio.run(run())

    assert "Failed to scan runnable plugin tasks: status=failed" in caplog.text
    assert "Failed to restore plugin tasks" in caplog.text


def test_plugin_task_scheduler_restores_pending_sqlite_task(tmp_path) -> None:
    database_path = tmp_path / "plugin_tasks.db"

    async def run() -> None:
        first_plugin = _build_scheduler_plugin(asyncio.Event())
        first_runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(first_plugin)],
            plugin_task_database_path=database_path,
            register_builtin_plugins=False,
        )
        try:
            assert first_runtime.plugin_manager is not None
            await first_runtime.plugin_manager.execute_command(
                PluginCommandRequest(
                    command=BotCommand(raw_text="/schedule", name="schedule")
                )
            )
        finally:
            await first_runtime.close()

        await asyncio.sleep(0.1)

        called = asyncio.Event()
        second_plugin = _build_scheduler_plugin(called)
        second_runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(second_plugin)],
            plugin_task_database_path=database_path,
            register_builtin_plugins=False,
        )
        try:
            await asyncio.wait_for(called.wait(), timeout=1)
        finally:
            await second_runtime.close()

    asyncio.run(run())


def test_plugin_task_scheduler_worker_scan_claims_due_sqlite_task(tmp_path) -> None:
    async def run() -> None:
        store = await create_sqlite_plugin_task_store(tmp_path / "plugin_tasks.db")
        called = asyncio.Event()
        executor = _RecordingTaskExecutor(called)
        scheduler = ApplicationPluginTaskScheduler(
            store=store,
            lease_owner="worker-scan",
            lease_seconds=0.1,
            scan_interval_seconds=0.01,
        )
        scheduler.register_task(
            "thirdparty.tasks",
            PluginTaskDefinition(name="conversation_end"),
            executor,
        )
        await scheduler.start()
        try:
            now = datetime.now(UTC)
            await store.add_task(
                PluginScheduledTask(
                    task_id="due-task",
                    plugin_id="thirdparty.tasks",
                    task_name="conversation_end",
                    run_at=now - timedelta(seconds=1),
                    payload={"user_id": "user-1"},
                    created_at=now,
                    updated_at=now,
                )
            )

            await asyncio.wait_for(called.wait(), timeout=1)
            tasks = await _wait_for_task_status(
                scheduler,
                plugin_id="thirdparty.tasks",
                task_name="conversation_end",
                status=PluginTaskStatus.COMPLETED,
            )

            assert executor.payloads == [{"user_id": "user-1"}]
            assert tasks[0].task_id == "due-task"
            assert tasks[0].lease_owner is None
        finally:
            await scheduler.shutdown()

    asyncio.run(run())


def test_plugin_task_scheduler_retries_failed_sqlite_task(tmp_path) -> None:
    database_path = tmp_path / "plugin_tasks.db"

    async def run() -> None:
        now = datetime.now(UTC)
        store = await create_sqlite_plugin_task_store(database_path)
        try:
            await store.add_task(
                PluginScheduledTask(
                    task_id="failed-task",
                    plugin_id="thirdparty.tasks",
                    task_name="conversation_end",
                    run_at=now - timedelta(seconds=1),
                    payload={"user_id": "user-1"},
                    key="retry-user-1",
                    status=PluginTaskStatus.FAILED,
                    last_error="boom",
                    created_at=now,
                    updated_at=now,
                )
            )
        finally:
            await store.close()

        called = asyncio.Event()
        plugin = _build_scheduler_plugin(called)
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            plugin_task_database_path=database_path,
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_task_scheduler is not None
            new_task_id = await runtime.plugin_task_scheduler.retry_task("failed-task")

            assert new_task_id.startswith("thirdparty.tasks:conversation_end:")
            await asyncio.wait_for(called.wait(), timeout=1)
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_task_scheduler_auto_retries_failed_task(tmp_path) -> None:
    database_path = tmp_path / "plugin_tasks.db"

    async def run() -> None:
        called = asyncio.Event()
        plugin = _build_retry_plugin()

        nonlocal_attempts = {"count": 0}

        @plugin.task(
            "flaky",
            max_retries=1,
            retry_backoff_seconds=0.01,
        )
        async def flaky(request):
            nonlocal_attempts["count"] += 1
            if nonlocal_attempts["count"] == 1:
                raise RuntimeError("boom")
            called.set()

        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            plugin_task_database_path=database_path,
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_task_scheduler is not None
            await runtime.plugin_task_scheduler.schedule_once(
                "thirdparty.retry",
                "flaky",
                delay_seconds=0,
            )
            await asyncio.wait_for(called.wait(), timeout=1)
            assert nonlocal_attempts["count"] == 2
            tasks = await _wait_for_task_status(
                runtime.plugin_task_scheduler,
                plugin_id="thirdparty.retry",
                task_name="flaky",
                status=PluginTaskStatus.COMPLETED,
            )
            assert tasks[0].status == PluginTaskStatus.COMPLETED
            assert tasks[0].attempt == 1
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_task_scheduler_times_out_task(tmp_path) -> None:
    database_path = tmp_path / "plugin_tasks.db"

    async def run() -> None:
        plugin = _build_retry_plugin()

        @plugin.task("slow", timeout_seconds=0.01)
        async def slow(request):
            await asyncio.sleep(1)

        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            plugin_task_database_path=database_path,
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_task_scheduler is not None
            await runtime.plugin_task_scheduler.schedule_once(
                "thirdparty.retry",
                "slow",
                delay_seconds=0,
            )
            await asyncio.sleep(0.1)
            tasks = await runtime.plugin_task_scheduler.list_tasks(
                plugin_id="thirdparty.retry",
                task_name="slow",
            )
            assert tasks[0].status == PluginTaskStatus.FAILED
            assert tasks[0].last_error is not None
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_task_scheduler_limits_task_concurrency(tmp_path) -> None:
    database_path = tmp_path / "plugin_tasks.db"

    async def run() -> None:
        active = 0
        max_active = 0
        completed = asyncio.Event()
        plugin = _build_retry_plugin()

        @plugin.task("serial", max_concurrent_runs=1)
        async def serial(request):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.03)
            active -= 1
            if request.payload.get("last"):
                completed.set()

        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            plugin_task_database_path=database_path,
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_task_scheduler is not None
            await runtime.plugin_task_scheduler.schedule_once(
                "thirdparty.retry",
                "serial",
                delay_seconds=0,
            )
            await runtime.plugin_task_scheduler.schedule_once(
                "thirdparty.retry",
                "serial",
                delay_seconds=0,
                payload={"last": True},
            )
            await asyncio.wait_for(completed.wait(), timeout=1)
            assert max_active == 1
        finally:
            await runtime.close()

    asyncio.run(run())


def _build_scheduler_plugin(called: asyncio.Event) -> CyreneBot:
    manifest = PluginManifest(
        plugin_id="thirdparty.tasks",
        name="Tasks",
        description="Tasks plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.BOT_COMMAND, PluginCapability.TASK],
        permissions=[PluginPermission.TASK],
    )
    plugin = CyreneBot(manifest)

    @plugin.task("conversation_end")
    async def conversation_end(request):
        if request.payload == {"user_id": "user-1"}:
            called.set()

    @plugin.command("/schedule")
    async def schedule(request, tasks=Depends("tasks")):
        await tasks.schedule_once(
            "conversation_end",
            delay_seconds=0.05,
            payload={"user_id": "user-1"},
            key="user-1",
        )
        return PluginCommandResult()

    return plugin


def _build_retry_plugin() -> CyreneBot:
    return CyreneBot(
        PluginManifest(
            plugin_id="thirdparty.retry",
            name="Retry",
            description="Retry plugin.",
            entrypoint="plugin.py",
            capabilities=[PluginCapability.TASK],
            permissions=[PluginPermission.TASK],
        )
    )


async def _wait_for_task_status(
    scheduler,
    *,
    plugin_id: str,
    task_name: str,
    status: PluginTaskStatus,
) -> list[PluginScheduledTask]:
    deadline = asyncio.get_running_loop().time() + 1
    while True:
        tasks = await scheduler.list_tasks(plugin_id=plugin_id, task_name=task_name)
        if tasks and tasks[0].status == status:
            return tasks
        if asyncio.get_running_loop().time() >= deadline:
            return tasks
        await asyncio.sleep(0.01)
