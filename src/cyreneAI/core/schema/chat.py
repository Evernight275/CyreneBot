from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.message import Message
from cyreneAI.core.schema.tool import ToolCall, ToolChoice, ToolDefinition
from cyreneAI.core.schema.usage import TokenUsage


class ChatFinishReason(StrEnum):
    """
    聊天结束原因
    """

    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"
    UNKNOWN = "unknown"


class ChatRequest(CyreneAISchema):
    """
    聊天请求schema
    """

    provider_id: str
    model: str
    messages: list[Message]

    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False

    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None

    tools: list[ToolDefinition] | None = None
    tool_choice: ToolChoice | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(CyreneAISchema):
    provider_id: str
    model: str | None = None

    message: Message | None = None
    tool_calls: list[ToolCall] = []

    finish_reason: ChatFinishReason = ChatFinishReason.UNKNOWN
    usage: TokenUsage | None = None

    raw: dict[str, Any] | None = None
