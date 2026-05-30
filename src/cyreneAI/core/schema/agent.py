from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.chat import ChatRequest, ChatResponse
from cyreneAI.core.schema.context import (
    ContextBudget,
    ContextSegment,
    ContextSnapshot,
)
from cyreneAI.core.schema.message import Message
from cyreneAI.core.schema.tool import ToolCall, ToolChoice, ToolResult


class AgentStopReason(StrEnum):
    """
    Agent 运行停止原因。
    """

    FINAL_RESPONSE = "final_response"
    MAX_STEPS = "max_steps"


class AgentRunRequest(CyreneAISchema):
    """
    最小 Agent Loop 请求。
    """

    session_id: str
    provider_id: str
    model: str
    goal: str | None = None
    messages: list[Message] = []
    context_budget: ContextBudget | None = None
    additional_context_segments: list[ContextSegment] = []

    max_steps: int = Field(default=4, ge=1)
    allowed_tool_names: list[str] | None = None
    tool_choice: ToolChoice | None = None

    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False

    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentStep(CyreneAISchema):
    """
    Agent Loop 的一次模型决策与工具执行记录。
    """

    index: int
    request: ChatRequest
    response: ChatResponse
    tool_calls: list[ToolCall] = []
    tool_results: list[ToolResult] = []


class AgentRunResult(CyreneAISchema):
    """
    最小 Agent Loop 结果。
    """

    response: ChatResponse
    steps: list[AgentStep] = []
    context_snapshot: ContextSnapshot
    completed: bool
    stop_reason: AgentStopReason
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AgentRunRequest",
    "AgentRunResult",
    "AgentStep",
    "AgentStopReason",
]
