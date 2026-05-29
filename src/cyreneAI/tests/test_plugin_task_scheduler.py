from __future__ import annotations

import asyncio

from cyreneAI.bootstrap import build_cyrene_ai_runtime
from cyreneAI.core.schema.bot import BotCommand
from cyreneAI.core.schema.plugin import (
    PluginCapability,
    PluginCommandRequest,
    PluginCommandResult,
    PluginManifest,
    PluginPermission,
)
from cyreneAI.api import CyreneBot, Depends


class _FakePluginLoader:
    def __init__(self, *modules: object) -> None:
        self._modules = list(modules)

    def load(self) -> list[object]:
        return self._modules


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
