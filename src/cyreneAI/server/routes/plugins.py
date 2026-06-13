from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import CyreneAIError
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginDefinition,
    PluginEventDefinition,
    PluginMiddlewareDefinition,
    PluginRuntimeDependencyInfo,
    PluginRuntimePermissionInfo,
    PluginSourceInfo,
    PluginStatusReport,
    PluginTaskDefinition,
)
from cyreneAI.core.schema.server import (
    PluginInspectionReport,
    PluginInstallReport,
    PluginOperationResult,
    PluginPathRequestBody,
    PluginPermissionAuditReport,
    PluginStorageKeysReport,
    PluginStorageValueReport,
    PluginTaskInstancesReport,
    PluginValidationReport,
)
from cyreneAI.server.dependencies import get_runtime, require_admin
from cyreneAI.server.errors import raise_http_error
from cyreneAI.server.plugin_admin import PluginAdminService

router = APIRouter(
    prefix="/plugins",
    tags=["plugins"],
    dependencies=[Depends(require_admin)],
)


def get_plugin_admin_service(
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> PluginAdminService:
    return PluginAdminService(runtime)


@router.get("", response_model=dict[str, list[PluginDefinition]])
async def list_plugins(
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> dict[str, list[PluginDefinition]]:
    try:
        return {"plugins": service.list_plugins()}
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get("/commands", response_model=dict[str, list[PluginCommandDefinition]])
async def list_plugin_commands(
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> dict[str, list[PluginCommandDefinition]]:
    try:
        return {"commands": service.list_commands()}
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get("/events", response_model=dict[str, list[PluginEventDefinition]])
async def list_plugin_events(
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> dict[str, list[PluginEventDefinition]]:
    try:
        return {"events": service.list_events()}
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get("/tasks", response_model=dict[str, list[PluginTaskDefinition]])
async def list_plugin_tasks(
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> dict[str, list[PluginTaskDefinition]]:
    try:
        return {"tasks": service.list_tasks()}
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get("/middlewares", response_model=dict[str, list[PluginMiddlewareDefinition]])
async def list_plugin_middlewares(
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> dict[str, list[PluginMiddlewareDefinition]]:
    try:
        return {"middlewares": service.list_middlewares()}
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get("/statuses", response_model=dict[str, list[PluginStatusReport]])
async def list_plugin_statuses(
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> dict[str, list[PluginStatusReport]]:
    try:
        return {"statuses": service.list_statuses()}
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get("/sources", response_model=dict[str, list[PluginSourceInfo]])
async def list_plugin_sources(
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> dict[str, list[PluginSourceInfo]]:
    try:
        return {"sources": service.list_sources()}
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get(
    "/runtime-capabilities",
    response_model=dict[
        str,
        list[PluginRuntimePermissionInfo] | list[PluginRuntimeDependencyInfo],
    ],
)
async def list_plugin_runtime_capabilities(
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> dict[str, list[PluginRuntimePermissionInfo] | list[PluginRuntimeDependencyInfo]]:
    try:
        return service.runtime_capabilities()
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.post("/validate-path", response_model=PluginValidationReport)
async def validate_plugin_path(
    body: PluginPathRequestBody,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginValidationReport:
    try:
        return service.validate_path(body)
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.post("/install-path", response_model=PluginInstallReport)
async def install_plugin_path(
    body: PluginPathRequestBody,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginInstallReport:
    try:
        return service.install_path(body)
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get("/tasks/instances", response_model=PluginTaskInstancesReport)
async def list_plugin_task_instances(
    plugin_id: str | None = None,
    task_name: str | None = None,
    status: list[str] | None = Query(default=None),
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginTaskInstancesReport:
    try:
        return await service.list_task_instances(
            plugin_id=plugin_id,
            task_name=task_name,
            status=status,
        )
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=PluginOperationResult,
)
async def cancel_plugin_task(
    task_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginOperationResult:
    try:
        return await service.cancel_task(task_id)
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.post(
    "/tasks/{task_id}/retry",
    response_model=PluginOperationResult,
)
async def retry_plugin_task(
    task_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginOperationResult:
    try:
        return await service.retry_task(task_id)
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get("/{plugin_id}", response_model=PluginDefinition)
async def get_plugin(
    plugin_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginDefinition:
    try:
        return service.get_plugin(plugin_id)
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get("/{plugin_id}/inspect", response_model=PluginInspectionReport)
async def inspect_plugin(
    plugin_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginInspectionReport:
    try:
        return service.inspect_plugin(plugin_id)
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.post("/{plugin_id}/disable", response_model=PluginDefinition)
async def disable_plugin(
    plugin_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginDefinition:
    try:
        return service.disable_plugin(plugin_id)
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.post("/{plugin_id}/enable", response_model=PluginDefinition)
async def enable_plugin(
    plugin_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginDefinition:
    try:
        return service.enable_plugin(plugin_id)
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.post("/{plugin_id}/reload", response_model=PluginOperationResult)
async def reload_plugin(
    plugin_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginOperationResult:
    try:
        return service.reload_plugin(plugin_id)
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get(
    "/{plugin_id}/commands",
    response_model=dict[str, list[PluginCommandDefinition]],
)
async def list_single_plugin_commands(
    plugin_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> dict[str, list[PluginCommandDefinition]]:
    try:
        return {"commands": service.list_plugin_commands(plugin_id)}
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get(
    "/{plugin_id}/events",
    response_model=dict[str, list[PluginEventDefinition]],
)
async def list_single_plugin_events(
    plugin_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> dict[str, list[PluginEventDefinition]]:
    try:
        return {"events": service.list_plugin_events(plugin_id)}
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get(
    "/{plugin_id}/tasks",
    response_model=dict[str, list[PluginTaskDefinition]],
)
async def list_single_plugin_tasks(
    plugin_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> dict[str, list[PluginTaskDefinition]]:
    try:
        return {"tasks": service.list_plugin_tasks(plugin_id)}
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get(
    "/{plugin_id}/middlewares",
    response_model=dict[str, list[PluginMiddlewareDefinition]],
)
async def list_single_plugin_middlewares(
    plugin_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> dict[str, list[PluginMiddlewareDefinition]]:
    try:
        return {"middlewares": service.list_plugin_middlewares(plugin_id)}
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get("/{plugin_id}/status", response_model=PluginStatusReport)
async def get_plugin_status(
    plugin_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginStatusReport:
    try:
        return service.get_plugin_status(plugin_id)
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get(
    "/{plugin_id}/permission-audit",
    response_model=PluginPermissionAuditReport,
)
async def list_plugin_permission_audit(
    plugin_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginPermissionAuditReport:
    try:
        return service.list_permission_audit(plugin_id)
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get(
    "/{plugin_id}/storage",
    response_model=PluginStorageKeysReport,
)
async def list_plugin_storage_keys(
    plugin_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginStorageKeysReport:
    try:
        return await service.list_storage_keys(plugin_id)
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.get(
    "/{plugin_id}/storage/{key}",
    response_model=PluginStorageValueReport,
)
async def get_plugin_storage_value(
    plugin_id: str,
    key: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginStorageValueReport:
    try:
        return await service.get_storage_value(plugin_id, key)
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.delete(
    "/{plugin_id}/storage/{key}",
    response_model=PluginOperationResult,
)
async def delete_plugin_storage_value(
    plugin_id: str,
    key: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginOperationResult:
    try:
        return await service.delete_storage_value(plugin_id, key)
    except CyreneAIError as exc:
        raise_http_error(exc)


@router.delete(
    "/{plugin_id}/storage",
    response_model=PluginOperationResult,
)
async def clear_plugin_storage(
    plugin_id: str,
    service: PluginAdminService = Depends(get_plugin_admin_service),
) -> PluginOperationResult:
    try:
        return await service.clear_storage(plugin_id)
    except CyreneAIError as exc:
        raise_http_error(exc)
