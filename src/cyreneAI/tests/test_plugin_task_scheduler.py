from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from cyreneAI.api import CyreneBot, Depends
from cyreneAI.application.plugins.tasks import ApplicationPluginTaskScheduler
from cyreneAI.bootstrap import build_cyrene_ai_runtime
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
