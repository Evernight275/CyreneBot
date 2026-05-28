from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)


class HTTPMessage(CyreneAISchema):
    role: MessageRole
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_core_message(self) -> Message:
        return Message(
            role=self.role,
            content=(
                [
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text=self.content,
                    )
                ]
                if self.content is not None
                else None
            ),
            name=self.name,
            tool_call_id=self.tool_call_id,
            metadata=self.metadata.copy(),
        )


class ChatRequestBody(CyreneAISchema):
    provider_id: str
    model: str
    messages: list[HTTPMessage]
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
    metadata: dict[str, Any] = Field(default_factory=dict)
