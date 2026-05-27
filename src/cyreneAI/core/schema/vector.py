from __future__ import annotations

from typing import Any

from pydantic import Field

from cyreneAI.core.schema.base import CyreneAISchema


class VectorRecord(CyreneAISchema):
    """
    向量记录schema
    """

    record_id: str
    vector: list[float] = Field(min_length=1)
    content: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VectorQuery(CyreneAISchema):
    """
    向量查询schema
    """

    vector: list[float] = Field(min_length=1)
    top_k: int = Field(default=5, ge=1)
    filters: dict[str, Any] = Field(default_factory=dict)
    min_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VectorSearchMatch(CyreneAISchema):
    """
    向量检索命中schema
    """

    record: VectorRecord
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class VectorSearchResult(CyreneAISchema):
    """
    向量检索结果schema
    """

    matches: list[VectorSearchMatch] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
