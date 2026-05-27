from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import CyreneAIError
from cyreneAI.server.dependencies import get_runtime

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("")
async def list_providers(
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict[str, list[dict]]:
    return {
        "providers": [
            info.model_dump(mode="json")
            for info in runtime.provider_manager.list_running()
        ]
    }


@router.get("/{provider_id}/models")
async def list_provider_models(
    provider_id: str,
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict[str, list[dict]]:
    try:
        models = await runtime.provider_manager.list_models(provider_id)
    except CyreneAIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "models": [
            model.model_dump(mode="json")
            for model in models
        ]
    }
