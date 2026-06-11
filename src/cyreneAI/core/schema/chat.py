from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.message import Message
from cyreneAI.core.schema.tool import ToolCall, ToolChoice, ToolDefinition, ToolResult
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


class ToolCallDelta(CyreneAISchema):
    """
    流式工具调用增量。

    provider 在流式输出里按片段下发工具调用，index 用于把分散的片段拼回同一个调用。
    """

    index: int
    id: str | None = None
    name: str | None = None
    arguments: str | None = None


class ChatStreamChunk(CyreneAISchema):
    """
    流式聊天增量片段。

    每个片段携带文本增量、工具调用增量或终止信息之一；done=True 标记该轮结束。
    """

    provider_id: str
    model: str | None = None

    delta_text: str | None = None
    reasoning_delta: str | None = None
    tool_call_deltas: list[ToolCallDelta] = Field(default_factory=list)

    finish_reason: ChatFinishReason | None = None
    usage: TokenUsage | None = None
    done: bool = False


class ChatStreamEventType(StrEnum):
    """
    编排层流式事件类型。
    """

    DELTA = "delta"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    DONE = "done"
    ERROR = "error"


class ChatStreamEvent(CyreneAISchema):
    """
    编排层向上游下发的流式事件。

    - DELTA：文本/思考增量（delta_text / reasoning_delta）。
    - TOOL_CALL：本轮解析出的完整工具调用列表（tool_calls）。
    - TOOL_RESULT：工具执行结果（tool_results）。
    - DONE：本次聊天结束，携带最终回复文本、finish_reason、usage。
    - ERROR：出错，detail 描述原因。
    """

    type: ChatStreamEventType

    delta_text: str | None = None
    reasoning_delta: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)

    content: str | None = None
    finish_reason: ChatFinishReason | None = None
    usage: TokenUsage | None = None
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
