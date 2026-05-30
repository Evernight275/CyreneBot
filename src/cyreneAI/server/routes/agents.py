from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cyreneAI.application.agent.orchestrator import (
    AgentOrchestrator,
    AgentRunRequest,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import CyreneAIError
from cyreneAI.server.dependencies import get_runtime, require_admin
from cyreneAI.server.schemas import AgentRunRequestBody

router = APIRouter(
    prefix="/agents",
    tags=["agents"],
    dependencies=[Depends(require_admin)],
)


@router.post("/run")
async def run_agent(
    body: AgentRunRequestBody,
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict:
    try:
        result = await AgentOrchestrator(runtime).run(
            AgentRunRequest(
                session_id=body.metadata.get("session_id", "http"),
                provider_id=body.provider_id,
                model=body.model,
                goal=body.goal,
                messages=[
                    message.to_core_message()
                    for message in body.messages
                ],
                context_budget=body.context_budget,
                additional_context_segments=body.additional_context_segments,
                max_steps=body.max_steps,
                allowed_tool_names=body.allowed_tool_names,
                tool_choice=body.tool_choice,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                metadata=body.metadata.copy(),
            )
        )
    except CyreneAIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")
