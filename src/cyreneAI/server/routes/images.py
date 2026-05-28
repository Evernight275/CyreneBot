from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cyreneAI.application.generation.image_orchestrator import (
    ApplicationImageGenerationRequest,
    ImageGenerationOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import CyreneAIError
from cyreneAI.server.dependencies import get_runtime
from cyreneAI.server.schemas import ImageGenerationRequestBody

router = APIRouter(prefix="/images", tags=["images"])


@router.post("/generate")
async def generate_image(
    body: ImageGenerationRequestBody,
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict:
    try:
        result = await ImageGenerationOrchestrator(runtime).generate_image(
            ApplicationImageGenerationRequest(
                provider_id=body.provider_id,
                model=body.model,
                prompt=body.prompt,
                count=body.count,
                size=body.size,
                quality=body.quality,
                response_format=body.response_format,
                metadata=body.metadata.copy(),
            )
        )
    except CyreneAIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")
