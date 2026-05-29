from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.plugin.runtime_capabilities import (
    list_plugin_runtime_dependencies,
    list_plugin_runtime_permissions,
)
from cyreneAI.core.plugin.manager import PluginManager
from cyreneAI.server.dependencies import get_runtime, require_admin


router = APIRouter(
    prefix="/plugins",
    tags=["plugins"],
    dependencies=[Depends(require_admin)],
)


@router.get("")
async def list_plugins(
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict[str, list[dict]]:
    manager = _get_plugin_manager(runtime)
    return {
        "plugins": [
            plugin.model_dump(mode="json")
            for plugin in manager.list_plugins()
        ]
    }


@router.get("/commands")
async def list_plugin_commands(
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict[str, list[dict]]:
    manager = _get_plugin_manager(runtime)
    return {
        "commands": [
            command.model_dump(mode="json")
            for command in manager.list_commands()
        ]
    }


@router.get("/events")
async def list_plugin_events(
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict[str, list[dict]]:
    manager = _get_plugin_manager(runtime)
    return {
        "events": [
            event.model_dump(mode="json")
            for event in manager.list_events()
        ]
    }


@router.get("/tasks")
async def list_plugin_tasks(
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict[str, list[dict]]:
    manager = _get_plugin_manager(runtime)
    return {
        "tasks": [
            task.model_dump(mode="json")
            for task in manager.list_tasks()
        ]
    }


@router.get("/statuses")
async def list_plugin_statuses(
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict[str, list[dict]]:
    manager = _get_plugin_manager(runtime)
    return {
        "statuses": [
            status.model_dump(mode="json")
            for status in manager.list_statuses()
        ]
    }


@router.get("/runtime-capabilities")
async def list_plugin_runtime_capabilities() -> dict[str, list[dict]]:
    return {
        "permissions": [
            item.model_dump(mode="json")
            for item in list_plugin_runtime_permissions()
        ],
        "dependencies": [
            item.model_dump(mode="json")
            for item in list_plugin_runtime_dependencies()
        ],
    }


def _get_plugin_manager(runtime: CyreneAIRuntime) -> PluginManager:
    if runtime.plugin_manager is None:
        raise HTTPException(status_code=503, detail="Plugin manager is not configured")
    return runtime.plugin_manager
