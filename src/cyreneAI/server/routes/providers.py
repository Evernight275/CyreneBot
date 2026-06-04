from __future__ import annotations

from typing import Any, NoReturn, cast

from fastapi import APIRouter, Depends, HTTPException

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import (
    ConflictError,
    CyreneAIError,
    NotFoundError,
    StateError,
)
from cyreneAI.core.errors.provider import ProviderError
from cyreneAI.core.schema.provider import (
    ProviderAdminStatus,
    ProviderConfig,
    ProviderConfigSummary,
    ProviderConnectionCheckResult,
    ProviderInfo,
    ProviderModel,
    ProviderOperationResult,
)
from cyreneAI.server.dependencies import get_runtime, require_admin
from cyreneAI.server.provider_admin import ProviderAdminService

router = APIRouter(
    prefix="/providers",
    tags=["providers"],
    dependencies=[Depends(require_admin)],
)


def get_provider_admin_service(
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> ProviderAdminService:
    return ProviderAdminService(runtime)


@router.get("")
async def list_providers(
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict[str, list[dict[str, Any]]]:
    return {
        "providers": [
            cast(dict[str, Any], info.model_dump(mode="json"))
            for info in runtime.provider_manager.list_running()
        ]
    }


@router.get("/catalog", response_model=dict[str, list[ProviderInfo]])
async def list_provider_catalog(
    service: ProviderAdminService = Depends(get_provider_admin_service),
) -> dict[str, list[ProviderInfo]]:
    try:
        return {"providers": service.list_catalog()}
    except CyreneAIError as exc:
        _raise_provider_http_exception(exc)


@router.get("/configs", response_model=dict[str, list[ProviderConfigSummary]])
async def list_provider_configs(
    service: ProviderAdminService = Depends(get_provider_admin_service),
) -> dict[str, list[ProviderConfigSummary]]:
    try:
        return {"configs": await service.list_configs()}
    except CyreneAIError as exc:
        _raise_provider_http_exception(exc)


@router.get("/statuses", response_model=dict[str, list[ProviderAdminStatus]])
async def list_provider_statuses(
    service: ProviderAdminService = Depends(get_provider_admin_service),
) -> dict[str, list[ProviderAdminStatus]]:
    try:
        return {"providers": await service.list_statuses()}
    except CyreneAIError as exc:
        _raise_provider_http_exception(exc)


@router.get("/{provider_id}", response_model=ProviderAdminStatus)
async def inspect_provider(
    provider_id: str,
    service: ProviderAdminService = Depends(get_provider_admin_service),
) -> ProviderAdminStatus:
    try:
        return await service.inspect(provider_id)
    except CyreneAIError as exc:
        _raise_provider_http_exception(exc)


@router.put("/{provider_id}/config", response_model=ProviderAdminStatus)
async def upsert_provider_config(
    provider_id: str,
    body: ProviderConfig,
    service: ProviderAdminService = Depends(get_provider_admin_service),
) -> ProviderAdminStatus:
    try:
        return await service.upsert_config(provider_id, body)
    except CyreneAIError as exc:
        _raise_provider_http_exception(exc)


@router.delete("/{provider_id}/config", response_model=ProviderOperationResult)
async def delete_provider_config(
    provider_id: str,
    service: ProviderAdminService = Depends(get_provider_admin_service),
) -> ProviderOperationResult:
    try:
        return await service.delete_config(provider_id)
    except CyreneAIError as exc:
        _raise_provider_http_exception(exc)


@router.post("/{provider_id}/start", response_model=ProviderOperationResult)
async def start_provider(
    provider_id: str,
    service: ProviderAdminService = Depends(get_provider_admin_service),
) -> ProviderOperationResult:
    try:
        return await service.start(provider_id)
    except CyreneAIError as exc:
        _raise_provider_http_exception(exc)


@router.post("/{provider_id}/stop", response_model=ProviderOperationResult)
async def stop_provider(
    provider_id: str,
    service: ProviderAdminService = Depends(get_provider_admin_service),
) -> ProviderOperationResult:
    try:
        return await service.stop(provider_id)
    except CyreneAIError as exc:
        _raise_provider_http_exception(exc)


@router.post("/{provider_id}/reload", response_model=ProviderOperationResult)
async def reload_provider(
    provider_id: str,
    service: ProviderAdminService = Depends(get_provider_admin_service),
) -> ProviderOperationResult:
    try:
        return await service.reload(provider_id)
    except CyreneAIError as exc:
        _raise_provider_http_exception(exc)


@router.post("/{provider_id}/check", response_model=ProviderConnectionCheckResult)
async def check_provider(
    provider_id: str,
    service: ProviderAdminService = Depends(get_provider_admin_service),
) -> ProviderConnectionCheckResult:
    try:
        return await service.check(provider_id)
    except CyreneAIError as exc:
        _raise_provider_http_exception(exc)


@router.get("/{provider_id}/models", response_model=dict[str, list[ProviderModel]])
async def list_provider_models(
    provider_id: str,
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict[str, list[ProviderModel]]:
    try:
        models = await runtime.provider_manager.list_models(provider_id)
    except CyreneAIError as exc:
        _raise_provider_http_exception(exc)
    return {"models": models}


def _raise_provider_http_exception(exc: Exception) -> NoReturn:
    if isinstance(exc, NotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, StateError) and "not configured" in str(exc):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, StateError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ProviderError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc
