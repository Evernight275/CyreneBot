from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cyreneAI.application.channels.webhook_handler import (
    ApplicationChannelWebhookRequest,
    ChannelWebhookHandler,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import CyreneAIError
from cyreneAI.server.dependencies import get_runtime, require_admin
from cyreneAI.server.schemas import ChannelWebhookRequestBody

router = APIRouter(
    prefix="/channels",
    tags=["channels"],
    dependencies=[Depends(require_admin)],
)


@router.post("/{channel_id}/webhook")
async def handle_channel_webhook(
    channel_id: str,
    body: ChannelWebhookRequestBody,
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict:
    try:
        result = await ChannelWebhookHandler(runtime).handle(
            ApplicationChannelWebhookRequest(
                channel_id=channel_id,
                payload=body.payload.copy(),
                provider_id=body.provider_id,
                model=body.model,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                metadata=body.metadata.copy(),
            )
        )
    except CyreneAIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")
