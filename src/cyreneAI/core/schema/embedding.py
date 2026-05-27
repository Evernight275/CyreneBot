from __future__ import annotations

from typing import Any

from pydantic import Field

from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.usage import TokenUsage


class EmbeddingRequest(CyreneAISchema):
    """
    嵌入请求schema
    """

    provider_id: str
    model: str
    input: str | list[str]
    dimensions: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddingVector(CyreneAISchema):
    """
    嵌入向量schema
    """

    index: int = Field(ge=0)
    embedding: list[float]
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddingResponse(CyreneAISchema):
    """
    嵌入响应schema
    """

    provider_id: str
    model: str | None = None
    embeddings: list[EmbeddingVector] = Field(default_factory=list)
    usage: TokenUsage | None = None
    raw: dict[str, Any] | None = None
