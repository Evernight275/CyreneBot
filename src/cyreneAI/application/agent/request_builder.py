from __future__ import annotations

from cyreneAI.core.schema.agent import (
    AgentMemoryRetrievalConfig,
    AgentPlanningConfig,
    AgentRunRequest,
    AgentToolSelectionConfig,
)
from cyreneAI.core.schema.context import ContextBudget, ContextSegment
from cyreneAI.core.schema.message import Message
from cyreneAI.core.schema.tool import ToolChoice, ToolExecutionPolicy


def build_agent_run_request(
    *,
    session_id: str,
    provider_id: str,
    model: str,
    goal: str | None = None,
    messages: list[Message] | None = None,
    context_budget: ContextBudget | None = None,
    additional_context_segments: list[ContextSegment] | None = None,
    max_steps: int = 4,
    required_skill_names: list[str] | None = None,
    max_skills: int | None = None,
    allowed_tool_names: list[str] | None = None,
    tool_execution_policy: ToolExecutionPolicy | None = None,
    planning: AgentPlanningConfig | None = None,
    tool_selection: AgentToolSelectionConfig | None = None,
    memory_retrieval: AgentMemoryRetrievalConfig | None = None,
    tool_choice: ToolChoice | None = None,
    max_tool_calls_per_step: int | None = None,
    max_total_tool_calls: int | None = None,
    max_tool_result_chars: int | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    stream: bool = False,
    metadata: dict[str, object] | None = None,
) -> AgentRunRequest:
    return AgentRunRequest(
        session_id=session_id,
        provider_id=provider_id,
        model=model,
        goal=goal,
        messages=list(messages or []),
        context_budget=context_budget,
        additional_context_segments=list(additional_context_segments or []),
        max_steps=max_steps,
        required_skill_names=list(required_skill_names or []),
        max_skills=max_skills,
        allowed_tool_names=allowed_tool_names,
        tool_execution_policy=tool_execution_policy,
        planning=planning,
        tool_selection=tool_selection,
        memory_retrieval=memory_retrieval,
        tool_choice=tool_choice,
        max_tool_calls_per_step=max_tool_calls_per_step,
        max_total_tool_calls=max_total_tool_calls,
        max_tool_result_chars=max_tool_result_chars,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=stream,
        metadata=dict(metadata or {}),
    )


__all__ = ["build_agent_run_request"]
