from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from cyreneAI.core.errors.plugin import (
    PluginConfigurationError,
    PluginNotFoundError,
    PluginStateError,
)
from cyreneAI.core.plugin.plugin_protocol import (
    PluginTaskExecutorProtocol,
    PluginTaskNamespaceProtocol,
    PluginTaskStoreProtocol,
)
from cyreneAI.core.schema.plugin import (
    PluginScheduledTask,
    PluginTaskDefinition,
    PluginTaskRequest,
    PluginTaskStatus,
)

logger = logging.getLogger(__name__)


class ApplicationPluginTaskScheduler:
    """
    application 层的插件后台任务调度器。
    """

    def __init__(self, store: PluginTaskStoreProtocol | None = None) -> None:
        self._definitions: dict[tuple[str, str], PluginTaskDefinition] = {}
        self._executors: dict[tuple[str, str], PluginTaskExecutorProtocol] = {}
        self._managed_tasks: dict[str, asyncio.Task[None]] = {}
        self._task_keys: dict[tuple[str, str], str] = {}
        self._store = store
        self._started = False

    def namespace(self, plugin_id: str) -> PluginTaskNamespaceProtocol:
        return _ApplicationPluginTaskNamespace(self, plugin_id)

    def register_task(
        self,
        plugin_id: str,
        definition: PluginTaskDefinition,
        executor: PluginTaskExecutorProtocol,
    ) -> None:
        normalized_name = _normalize_task_name(definition.name)
        if not normalized_name:
            raise PluginConfigurationError("插件任务 name 不能为空")
        _validate_task_definition(definition)

        key = (plugin_id, normalized_name)
        if key in self._definitions:
            raise PluginConfigurationError(
                f"插件任务 {plugin_id}:{normalized_name} 重复注册"
            )

        stored_definition = definition.model_copy(update={"name": normalized_name})
        self._definitions[key] = stored_definition
        self._executors[key] = executor

        if self._started and stored_definition.enabled:
            self._schedule_declared_task(plugin_id, stored_definition)
            self._schedule_restore(plugin_id, stored_definition.name)

    def unregister_plugin(self, plugin_id: str) -> None:
        """
        注销指定插件的任务定义，并取消尚未完成的内存任务。
        """
        for key in list(self._definitions):
            if key[0] == plugin_id:
                self._definitions.pop(key, None)
                self._executors.pop(key, None)

        for task_id, task in list(self._managed_tasks.items()):
            if task_id.startswith(f"{plugin_id}:"):
                self._managed_tasks.pop(task_id, None)
                task.cancel()

        for task_key in list(self._task_keys):
            if task_key[0] == plugin_id:
                self._task_keys.pop(task_key, None)

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for (plugin_id, _), definition in list(self._definitions.items()):
            if definition.enabled:
                self._schedule_declared_task(plugin_id, definition)
                self._schedule_restore(plugin_id, definition.name)

    async def shutdown(self) -> None:
        if not self._started and not self._managed_tasks:
            return
        self._started = False
        tasks = list(self._managed_tasks.values())
        self._managed_tasks.clear()
        self._task_keys.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._store is not None:
            await self._store.close()

    async def list_tasks(
        self,
        *,
        plugin_id: str | None = None,
        task_name: str | None = None,
        statuses: list[PluginTaskStatus] | None = None,
    ) -> list[PluginScheduledTask]:
        if self._store is None:
            return []
        return await self._store.list_tasks(
            plugin_id=plugin_id,
            task_name=_normalize_task_name(task_name) if task_name else None,
            statuses=statuses,
        )

    async def cancel_task(self, task_id: str) -> None:
        await self.cancel(task_id)

    async def retry_task(self, task_id: str) -> str:
        if self._store is None:
            raise PluginStateError("runtime 未配置 plugin task store")
        task_record = await self._store.get_task(task_id)
        if task_record.status != PluginTaskStatus.FAILED:
            raise PluginConfigurationError("只能重试 failed 插件任务")
        return await self.schedule_once(
            task_record.plugin_id,
            task_record.task_name,
            delay_seconds=0,
            payload=task_record.payload,
            key=task_record.key,
        )

    async def schedule_once(
        self,
        plugin_id: str,
        task_name: str,
        *,
        delay_seconds: float,
        payload: dict[str, Any] | None = None,
        key: str | None = None,
    ) -> str:
        if delay_seconds < 0:
            raise PluginConfigurationError("delay_seconds 不能为负数")

        definition = self._get_definition(plugin_id, task_name)
        normalized_key = key.strip() if isinstance(key, str) and key.strip() else None
        if normalized_key is not None:
            await self.cancel_key(plugin_id, normalized_key)

        now = datetime.now(UTC)
        task_id = f"{plugin_id}:{definition.name}:{uuid.uuid4().hex}"
        task_record = PluginScheduledTask(
            task_id=task_id,
            plugin_id=plugin_id,
            task_name=definition.name,
            run_at=now + timedelta(seconds=delay_seconds),
            payload=payload or {},
            key=normalized_key,
            created_at=now,
            updated_at=now,
        )
        if self._store is not None:
            await self._store.add_task(task_record)
        self._schedule_task_record(task_record)
        return task_id

    async def cancel(self, task_id: str) -> None:
        task = self._managed_tasks.pop(task_id, None)
        for task_key, keyed_task_id in list(self._task_keys.items()):
            if keyed_task_id == task_id:
                self._task_keys.pop(task_key, None)
        if self._store is not None:
            await self._store.cancel_task(task_id)
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def cancel_key(self, plugin_id: str, key: str) -> int:
        key = key.strip()
        if not key:
            return 0
        task_id = self._task_keys.get((plugin_id, key))
        if task_id is not None:
            await self.cancel(task_id)
            return 1
        if self._store is not None:
            return await self._store.cancel_task_key(plugin_id, key)
        return 0

    def _schedule_task_record(self, task_record: PluginScheduledTask) -> None:
        if task_record.task_id in self._managed_tasks:
            return
        task = asyncio.create_task(
            self._run_scheduled_task_record(task_record),
            name=f"plugin-task:{task_record.plugin_id}:{task_record.task_name}",
        )
        self._managed_tasks[task_record.task_id] = task
        if task_record.key is not None:
            self._task_keys[(task_record.plugin_id, task_record.key)] = (
                task_record.task_id
            )
        task.add_done_callback(lambda _: self._forget_task(task_record.task_id))

    def _schedule_declared_task(
        self,
        plugin_id: str,
        definition: PluginTaskDefinition,
    ) -> None:
        if (
            definition.interval_seconds is None
            and definition.daily_at is None
            and not definition.run_on_start
        ):
            return

        task_id = f"{plugin_id}:{definition.name}:managed"
        if task_id in self._managed_tasks:
            return

        task = asyncio.create_task(
            self._run_declared_loop(plugin_id, definition),
            name=f"plugin-task:{plugin_id}:{definition.name}:managed",
        )
        self._managed_tasks[task_id] = task
        task.add_done_callback(lambda _: self._forget_task(task_id))

    async def _run_declared_loop(
        self,
        plugin_id: str,
        definition: PluginTaskDefinition,
    ) -> None:
        if definition.run_on_start:
            await self._execute_declared_once(plugin_id, definition)

        if definition.interval_seconds is not None:
            while self._started:
                await asyncio.sleep(definition.interval_seconds)
                await self._execute_declared_once(plugin_id, definition)
            return

        if definition.daily_at is not None:
            while self._started:
                await asyncio.sleep(_seconds_until_daily_at(definition.daily_at))
                await self._execute_declared_once(plugin_id, definition)

    async def _execute_declared_once(
        self,
        plugin_id: str,
        definition: PluginTaskDefinition,
    ) -> None:
        try:
            await self._execute(plugin_id, definition.name, payload={})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Plugin declared task failed: plugin_id=%s task=%s status=failed",
                plugin_id,
                definition.name,
            )

    async def _run_scheduled_task_record(
        self,
        task_record: PluginScheduledTask,
    ) -> None:
        try:
            delay_seconds = max(
                0.0,
                (task_record.run_at - datetime.now(UTC)).total_seconds(),
            )
            await asyncio.sleep(delay_seconds)
            if self._store is not None:
                await self._store.update_task_status(
                    task_record.task_id,
                    PluginTaskStatus.RUNNING,
                )
            await self._execute(
                task_record.plugin_id,
                task_record.task_name,
                payload=task_record.payload,
            )
            if self._store is not None:
                await self._store.update_task_status(
                    task_record.task_id,
                    PluginTaskStatus.COMPLETED,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._store is not None:
                await self._store.update_task_status(
                    task_record.task_id,
                    PluginTaskStatus.FAILED,
                    last_error=str(exc),
                )
            logger.exception(
                "Plugin one-shot task failed: task_id=%s plugin_id=%s task=%s status=failed",
                task_record.task_id,
                task_record.plugin_id,
                task_record.task_name,
            )

    def _schedule_restore(self, plugin_id: str, task_name: str) -> None:
        if self._store is None:
            return
        restore_task_id = f"{plugin_id}:{task_name}:restore"
        if restore_task_id in self._managed_tasks:
            return
        task = asyncio.create_task(
            self._restore_pending_tasks(plugin_id, task_name),
            name=f"plugin-task:{plugin_id}:{task_name}:restore",
        )
        self._managed_tasks[restore_task_id] = task
        task.add_done_callback(lambda _: self._forget_task(restore_task_id))

    async def _restore_pending_tasks(self, plugin_id: str, task_name: str) -> None:
        if self._store is None:
            return
        try:
            task_records = await self._store.list_pending_tasks(
                plugin_id=plugin_id,
                task_name=task_name,
            )
            for task_record in task_records:
                if task_record.task_id in self._managed_tasks:
                    continue
                self._schedule_task_record(task_record)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to restore plugin tasks: plugin_id=%s task=%s status=failed",
                plugin_id,
                task_name,
            )

    async def _execute(
        self,
        plugin_id: str,
        task_name: str,
        *,
        payload: dict[str, Any],
    ) -> None:
        definition = self._get_definition(plugin_id, task_name)
        executor = self._executors[(plugin_id, definition.name)]
        await executor.execute(
            PluginTaskRequest(
                task=definition,
                payload=payload,
            )
        )

    def _get_definition(
        self,
        plugin_id: str,
        task_name: str,
    ) -> PluginTaskDefinition:
        normalized_name = _normalize_task_name(task_name)
        key = (plugin_id, normalized_name)
        definition = self._definitions.get(key)
        if definition is None:
            raise PluginNotFoundError(f"插件任务 {plugin_id}:{normalized_name} 不存在")
        return definition

    def _forget_task(self, task_id: str) -> None:
        self._managed_tasks.pop(task_id, None)
        for task_key, keyed_task_id in list(self._task_keys.items()):
            if keyed_task_id == task_id:
                self._task_keys.pop(task_key, None)


class _ApplicationPluginTaskNamespace:
    def __init__(
        self,
        scheduler: ApplicationPluginTaskScheduler,
        plugin_id: str,
    ) -> None:
        self._scheduler = scheduler
        self._plugin_id = plugin_id

    async def schedule_once(
        self,
        task_name: str,
        *,
        delay_seconds: float,
        payload: dict[str, Any] | None = None,
        key: str | None = None,
    ) -> str:
        return await self._scheduler.schedule_once(
            self._plugin_id,
            task_name,
            delay_seconds=delay_seconds,
            payload=payload,
            key=key,
        )

    async def cancel(self, task_id: str) -> None:
        await self._scheduler.cancel(task_id)

    async def cancel_key(self, key: str) -> int:
        return await self._scheduler.cancel_key(self._plugin_id, key)


def _normalize_task_name(value: str) -> str:
    return " ".join(value.strip().replace("/", " ").split()).lower()


def _validate_task_definition(definition: PluginTaskDefinition) -> None:
    if definition.interval_seconds is not None and definition.interval_seconds <= 0:
        raise PluginConfigurationError("interval_seconds 必须大于 0")
    if definition.interval_seconds is not None and definition.daily_at is not None:
        raise PluginConfigurationError(
            "插件任务不能同时声明 interval_seconds 和 daily_at"
        )
    if definition.daily_at is not None:
        _parse_daily_at(definition.daily_at)


def _parse_daily_at(value: str) -> tuple[int, int]:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise PluginConfigurationError("daily_at 必须使用 HH:MM 格式") from exc
    return parsed.hour, parsed.minute


def _seconds_until_daily_at(value: str) -> float:
    hour, minute = _parse_daily_at(value)
    now = datetime.now().astimezone()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


__all__ = ["ApplicationPluginTaskScheduler"]
