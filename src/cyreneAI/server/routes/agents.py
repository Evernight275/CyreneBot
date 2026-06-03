from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from cyreneAI.application.agent.history import (
    DEFAULT_AGENT_RUN_HISTORY_LIMIT,
    MAX_AGENT_RUN_HISTORY_LIMIT,
    AgentRunHistoryReader,
)
from cyreneAI.application.agent.orchestrator import (
    AgentOrchestrator,
)
from cyreneAI.application.agent.request_builder import build_agent_run_request
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import CyreneAIError, NotFoundError, StateError
from cyreneAI.server.dependencies import get_runtime, require_admin
from cyreneAI.server.schemas import AgentRunRequestBody

router = APIRouter(
    prefix="/agents",
    tags=["agents"],
    dependencies=[Depends(require_admin)],
)


@router.get("/runs")
async def list_agent_runs(
    session_id: str,
    limit: int = Query(
        default=DEFAULT_AGENT_RUN_HISTORY_LIMIT,
        ge=1,
        le=MAX_AGENT_RUN_HISTORY_LIMIT,
    ),
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict:
    try:
        result = await AgentRunHistoryReader(runtime).list_runs(
            session_id,
            limit=limit,
        )
    except StateError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CyreneAIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.get("/runs/{snapshot_id}")
async def get_agent_run(
    snapshot_id: str,
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict:
    try:
        result = await AgentRunHistoryReader(runtime).get_run(snapshot_id)
    except StateError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CyreneAIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.post("/run")
async def run_agent(
    body: AgentRunRequestBody,
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict:
    try:
        result = await AgentOrchestrator(runtime).run(
            build_agent_run_request(
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
                required_skill_names=body.required_skill_names,
                max_skills=body.max_skills,
                allowed_tool_names=body.allowed_tool_names,
                tool_execution_policy=body.tool_execution_policy,
                planning=body.planning,
                tool_selection=body.tool_selection,
                memory_retrieval=body.memory_retrieval,
                tool_choice=body.tool_choice,
                max_tool_calls_per_step=body.max_tool_calls_per_step,
                max_total_tool_calls=body.max_total_tool_calls,
                max_tool_result_chars=body.max_tool_result_chars,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                metadata=body.metadata.copy(),
            )
        )
    except CyreneAIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")
