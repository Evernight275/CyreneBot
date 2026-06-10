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
from cyreneAI.core.schema.skill import SkillInstructionBundle
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolChoice,
    ToolExecutionPolicy,
    ToolResult,
)


def _empty_messages() -> list[Message]:
    return []


def _empty_context_segments() -> list[ContextSegment]:
    return []


def _empty_tool_calls() -> list[ToolCall]:
    return []


def _empty_tool_results() -> list[ToolResult]:
    return []


def _empty_agent_steps() -> list["AgentStep"]:
    return []


def _empty_agent_plan_steps() -> list["AgentPlanStep"]:
    return []


def _empty_agent_run_history_items() -> list["AgentRunHistoryItem"]:
    return []


def _empty_agent_run_trace_items() -> list["AgentRunTraceItem"]:
    return []


def _empty_strings() -> list[str]:
    return []


class AgentStopReason(StrEnum):
    """
    Agent 运行停止原因。
    """

    FINAL_RESPONSE = "final_response"
    MAX_STEPS = "max_steps"
    TOOL_LIMIT = "tool_limit"


class AgentPlanningMode(StrEnum):
    """
    Agent planner 执行模式。
    """

    RULE_BASED = "rule_based"
    LLM = "llm"


class AgentPlanningConfig(CyreneAISchema):
    """
    Agent 运行提示配置。
    """

    enabled: bool = False
    mode: AgentPlanningMode = AgentPlanningMode.RULE_BASED
    instructions: str | None = None
    max_objectives: int = Field(default=4, ge=1)
    max_plan_steps: int = Field(default=6, ge=1, le=20)
    planner_provider_id: str | None = None
    planner_model: str | None = None
    replanning_enabled: bool = False
    max_replans: int = Field(default=1, ge=0, le=5)


class AgentToolSelectionConfig(CyreneAISchema):
    """
    Agent 运行期工具选择配置。
    """

    allowed_tool_names: list[str] | None = None
    denied_tool_names: list[str] = Field(default_factory=list)


class AgentMemoryRetrievalConfig(CyreneAISchema):
    """
    Agent 运行前记忆检索配置。
    """

    enabled: bool = False
    strict: bool = False
    query: str | None = None
    namespace: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float | None = None


class AgentPlanStep(CyreneAISchema):
    """
    Agent planner 产出的单个计划步骤。
    """

    index: int = Field(ge=0)
    objective: str
    action: str
    tool_names: list[str] = Field(default_factory=_empty_strings)
    skill_names: list[str] = Field(default_factory=_empty_strings)
    status: str = "pending"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentPlanConstraints(CyreneAISchema):
    """
    Agent plan 记录的工具与 skill 约束。
    """

    selected_tool_names: list[str] = Field(default_factory=_empty_strings)
    denied_tool_names: list[str] = Field(default_factory=_empty_strings)
    required_skill_names: list[str] = Field(default_factory=_empty_strings)
    selected_skill_names: list[str] = Field(default_factory=_empty_strings)
    max_skills: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentPlan(CyreneAISchema):
    """
    Agent 运行前生成的可审计计划。
    """

    goal: str | None = None
    objectives: list[str] = Field(default_factory=list)
    steps: list[AgentPlanStep] = Field(default_factory=_empty_agent_plan_steps)
    selected_tool_names: list[str] = Field(default_factory=list)
    constraints: AgentPlanConstraints = Field(default_factory=AgentPlanConstraints)
    memory_query: str | None = None
    instructions: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunRequest(CyreneAISchema):
    """
    最小 Agent Loop 请求。
    """

    session_id: str
    provider_id: str
    model: str
    goal: str | None = None
    messages: list[Message] = Field(default_factory=_empty_messages)
    context_budget: ContextBudget | None = None
    additional_context_segments: list[ContextSegment] = Field(
        default_factory=_empty_context_segments
    )

    max_steps: int = Field(default=4, ge=1)
    required_skill_names: list[str] = Field(default_factory=list)
    max_skills: int | None = None
    allowed_tool_names: list[str] | None = None
    tool_execution_policy: ToolExecutionPolicy | None = None
    planning: AgentPlanningConfig | None = None
    tool_selection: AgentToolSelectionConfig | None = None
    memory_retrieval: AgentMemoryRetrievalConfig | None = None
    tool_choice: ToolChoice | None = None
    max_tool_calls_per_step: int | None = Field(default=None, ge=1)
    max_total_tool_calls: int | None = Field(default=None, ge=1)
    max_tool_result_chars: int | None = Field(default=None, ge=1)

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
    tool_calls: list[ToolCall] = Field(default_factory=_empty_tool_calls)
    tool_results: list[ToolResult] = Field(default_factory=_empty_tool_results)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunResult(CyreneAISchema):
    """
    最小 Agent Loop 结果。
    """

    response: ChatResponse
    steps: list[AgentStep] = Field(default_factory=_empty_agent_steps)
    plan: AgentPlan | None = None
    skill_bundle: SkillInstructionBundle | None = None
    context_snapshot: ContextSnapshot
    completed: bool
    stop_reason: AgentStopReason
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunHistoryItem(CyreneAISchema):
    """
    Agent run 历史摘要。
    """

    snapshot_id: str
    session_id: str
    provider_id: str = "-"
    model: str = "-"
    finished_at: str = "-"
    completed: bool | None = None
    stop_reason: str = "-"
    step_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    tool_result_count: int = Field(default=0, ge=0)
    tool_error_count: int = Field(default=0, ge=0)
    tool_names: list[str] = Field(default_factory=_empty_strings)
    trace_item_count: int = Field(default=0, ge=0)
    last_assistant: str | None = None


class AgentRunHistoryListResult(CyreneAISchema):
    """
    Agent run 历史列表。
    """

    session_id: str
    limit: int = Field(default=10, ge=1, le=50)
    runs: list[AgentRunHistoryItem] = Field(
        default_factory=_empty_agent_run_history_items
    )


class AgentRunTraceItem(CyreneAISchema):
    """
    Agent run trace 的紧凑条目。
    """

    index: int = Field(ge=0)
    item_id: str
    item_type: str
    source: str
    role: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    text_preview: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunTraceResult(CyreneAISchema):
    """
    Agent run trace 详情。
    """

    run: AgentRunHistoryItem
    trace_items: list[AgentRunTraceItem] = Field(
        default_factory=_empty_agent_run_trace_items
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AgentMemoryRetrievalConfig",
    "AgentPlan",
    "AgentPlanConstraints",
    "AgentPlanStep",
    "AgentPlanningConfig",
    "AgentPlanningMode",
    "AgentRunHistoryItem",
    "AgentRunHistoryListResult",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentRunTraceItem",
    "AgentRunTraceResult",
    "AgentStep",
    "AgentStopReason",
    "AgentToolSelectionConfig",
]
