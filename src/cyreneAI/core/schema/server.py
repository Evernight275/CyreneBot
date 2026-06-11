from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from cyreneAI.core.schema.agent import (
    AgentMemoryRetrievalConfig,
    AgentPlanningConfig,
    AgentToolSelectionConfig,
)
from cyreneAI.core.schema.application import (
    BotMessageResponseMode,
    BotMessageTriggerMode,
)
from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.context import ContextBudget, ContextSegment
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginDefinition,
    PluginEventDefinition,
    PluginMiddlewareDefinition,
    PluginPermissionAuditRecord,
    PluginScheduledTask,
    PluginSourceInfo,
    PluginStatusReport,
    PluginTaskDefinition,
)
from cyreneAI.core.schema.tool import ToolChoice, ToolExecutionPolicy


def _empty_context_segments() -> list[ContextSegment]:
    return []


class HTTPMessage(CyreneAISchema):
    role: MessageRole
    content: str | None = None
    content_parts: list[ContentPart] | None = None
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_core_message(self) -> Message:
        if self.content_parts is not None:
            content = self.content_parts
        elif self.content is not None:
            content = [
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=self.content,
                )
            ]
        else:
            content = None
        return Message(
            role=self.role,
            content=content,
            name=self.name,
            tool_call_id=self.tool_call_id,
            metadata=self.metadata.copy(),
        )


def _empty_http_messages() -> list[HTTPMessage]:
    return []


class ChatRequestBody(CyreneAISchema):
    provider_id: str
    model: str
    messages: list[HTTPMessage]
    temperature: float | None = None
    max_tokens: int | None = None
    tool_choice: ToolChoice | None = None
    allowed_tool_names: list[str] | None = None
    tool_execution_policy: ToolExecutionPolicy | None = None
    max_tool_rounds: int = Field(default=1, ge=0)
    stream: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunRequestBody(CyreneAISchema):
    provider_id: str
    model: str
    goal: str | None = None
    messages: list[HTTPMessage] = Field(default_factory=_empty_http_messages)
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
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageGenerationRequestBody(CyreneAISchema):
    provider_id: str
    model: str
    prompt: str
    count: int = Field(default=1, ge=1)
    size: str | None = None
    quality: str | None = None
    response_format: Literal["url", "b64_json"] = "b64_json"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChannelWebhookRequestBody(CyreneAISchema):
    provider_id: str
    model: str
    payload: dict[str, Any]
    temperature: float | None = None
    max_tokens: int | None = None
    tool_choice: ToolChoice | None = None
    allowed_tool_names: list[str] | None = None
    tool_execution_policy: ToolExecutionPolicy | None = None
    max_tool_rounds: int = Field(default=1, ge=0)
    max_agent_steps: int = Field(default=4, ge=1)
    max_agent_tool_calls_per_step: int | None = Field(default=None, ge=1)
    max_agent_total_tool_calls: int | None = Field(default=None, ge=1)
    max_agent_tool_result_chars: int | None = Field(default=None, ge=1)
    required_skill_names: list[str] = Field(default_factory=list)
    max_skills: int | None = None
    agent_planning: AgentPlanningConfig | None = None
    agent_tool_selection: AgentToolSelectionConfig | None = None
    agent_memory_retrieval: AgentMemoryRetrievalConfig | None = None
    message_response_mode: BotMessageResponseMode = BotMessageResponseMode.CHAT
    message_trigger_mode: BotMessageTriggerMode = BotMessageTriggerMode.ALWAYS
    message_trigger_keywords: list[str] = Field(default_factory=list)
    message_trigger_mentions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ServerSettings(CyreneAISchema):
    """
    Server runtime settings.
    """

    admin_username: str | None = None
    admin_password: str | None = None
    auth_enabled: bool = True
    session_secret: str | None = None
    session_cookie_name: str = "cyrene_admin_session"
    session_ttl_seconds: int = 12 * 60 * 60


class PluginPathRequestBody(CyreneAISchema):
    path: str


class PluginOperationResult(CyreneAISchema):
    action: str
    accepted: bool = True
    plugin_id: str | None = None
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginInstallReport(CyreneAISchema):
    installed: list[PluginDefinition] = []
    sources: list[PluginSourceInfo] = []


class PluginInspectionReport(CyreneAISchema):
    definition: PluginDefinition
    status: PluginStatusReport | None = None
    source: PluginSourceInfo | None = None
    commands: list[PluginCommandDefinition] = []
    events: list[PluginEventDefinition] = []
    tasks: list[PluginTaskDefinition] = []
    middlewares: list[PluginMiddlewareDefinition] = []


class PluginValidationReport(CyreneAISchema):
    path: str
    valid: bool
    plugin_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PluginStorageKeysReport(CyreneAISchema):
    plugin_id: str
    keys: list[str] = Field(default_factory=list)


class PluginStorageValueReport(CyreneAISchema):
    plugin_id: str
    key: str
    value: Any


class PluginTaskInstancesReport(CyreneAISchema):
    tasks: list[PluginScheduledTask] = []


class PluginPermissionAuditReport(CyreneAISchema):
    records: list[PluginPermissionAuditRecord] = []


__all__ = [
    "AgentRunRequestBody",
    "ChannelWebhookRequestBody",
    "ChatRequestBody",
    "HTTPMessage",
    "ImageGenerationRequestBody",
    "PluginInstallReport",
    "PluginInspectionReport",
    "PluginOperationResult",
    "PluginPathRequestBody",
    "PluginPermissionAuditReport",
    "PluginStorageKeysReport",
    "PluginStorageValueReport",
    "PluginTaskInstancesReport",
    "PluginValidationReport",
    "ServerSettings",
]
