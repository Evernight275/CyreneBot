from __future__ import annotations

from typing import Any

from pydantic import Field

from cyreneAI.core.schema.base import CyreneAISchema


class Document(CyreneAISchema):
    """
    文档schema
    """

    document_id: str
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentChunk(CyreneAISchema):
    """
    文档分块schema
    """

    chunk_id: str
    document_id: str
    index: int = Field(ge=0)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
