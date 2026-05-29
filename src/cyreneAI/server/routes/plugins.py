from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.plugin.runtime_capabilities import (
    list_plugin_runtime_dependencies,
    list_plugin_runtime_permissions,
)
from cyreneAI.core.plugin.manager import PluginManager
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginDefinition,
    PluginEventDefinition,
    PluginRuntimeDependencyInfo,
    PluginRuntimePermissionInfo,
    PluginStatusReport,
    PluginTaskDefinition,
)
from cyreneAI.server.dependencies import get_runtime, require_admin


router = APIRouter(
    prefix="/plugins",
    tags=["plugins"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=dict[str, list[PluginDefinition]])
async def list_plugins(
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict[str, list[PluginDefinition]]:
    manager = _get_plugin_manager(runtime)
    return {"plugins": manager.list_plugins()}


@router.get("/commands", response_model=dict[str, list[PluginCommandDefinition]])
async def list_plugin_commands(
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict[str, list[PluginCommandDefinition]]:
    manager = _get_plugin_manager(runtime)
    return {"commands": manager.list_commands()}


@router.get("/events", response_model=dict[str, list[PluginEventDefinition]])
async def list_plugin_events(
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict[str, list[PluginEventDefinition]]:
    manager = _get_plugin_manager(runtime)
    return {"events": manager.list_events()}


@router.get("/tasks", response_model=dict[str, list[PluginTaskDefinition]])
async def list_plugin_tasks(
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict[str, list[PluginTaskDefinition]]:
    manager = _get_plugin_manager(runtime)
    return {"tasks": manager.list_tasks()}


@router.get("/statuses", response_model=dict[str, list[PluginStatusReport]])
async def list_plugin_statuses(
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict[str, list[PluginStatusReport]]:
    manager = _get_plugin_manager(runtime)
    return {"statuses": manager.list_statuses()}


@router.get(
    "/runtime-capabilities",
    response_model=dict[
        str,
        list[PluginRuntimePermissionInfo] | list[PluginRuntimeDependencyInfo],
    ],
)
async def list_plugin_runtime_capabilities() -> dict[
    str,
    list[PluginRuntimePermissionInfo] | list[PluginRuntimeDependencyInfo],
]:
    return {
        "permissions": list_plugin_runtime_permissions(),
        "dependencies": list_plugin_runtime_dependencies(),
    }


def _get_plugin_manager(runtime: CyreneAIRuntime) -> PluginManager:
    if runtime.plugin_manager is None:
        raise HTTPException(status_code=503, detail="Plugin manager is not configured")
    return runtime.plugin_manager
