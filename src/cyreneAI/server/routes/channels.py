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
                required_skill_names=body.required_skill_names,
                max_skills=body.max_skills,
                tool_choice=body.tool_choice,
                allowed_tool_names=body.allowed_tool_names,
                tool_execution_policy=body.tool_execution_policy,
                max_tool_rounds=body.max_tool_rounds,
                max_agent_steps=body.max_agent_steps,
                agent_planning=body.agent_planning,
                agent_tool_selection=body.agent_tool_selection,
                agent_memory_retrieval=body.agent_memory_retrieval,
                message_response_mode=body.message_response_mode,
                message_trigger_mode=body.message_trigger_mode,
                message_trigger_keywords=body.message_trigger_keywords,
                message_trigger_mentions=body.message_trigger_mentions,
                metadata=body.metadata.copy(),
            )
        )
    except CyreneAIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")
