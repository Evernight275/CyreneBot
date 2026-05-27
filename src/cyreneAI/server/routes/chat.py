from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cyreneAI.application.chat_orchestrator import (
    ApplicationChatRequest,
    ChatOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import CyreneAIError
from cyreneAI.server.dependencies import get_runtime
from cyreneAI.server.schemas import ChatRequestBody

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
async def chat(
    body: ChatRequestBody,
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict:
    try:
        result = await ChatOrchestrator(runtime).chat(
            ApplicationChatRequest(
                session_id=body.metadata.get("session_id", "http"),
                provider_id=body.provider_id,
                model=body.model,
                messages=[
                    message.to_core_message()
                    for message in body.messages
                ],
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                metadata=body.metadata.copy(),
            )
        )
    except CyreneAIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")
