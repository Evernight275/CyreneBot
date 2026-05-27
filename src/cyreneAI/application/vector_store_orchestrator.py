from __future__ import annotations

from typing import Any

from pydantic import Field

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import StateError
from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.vector import (
    VectorQuery,
    VectorRecord,
    VectorSearchResult,
)
from cyreneAI.core.vector.manager import VectorManager


class ApplicationVectorUpsertRequest(CyreneAISchema):
    """
    应用向量写入请求
    """

    records: list[VectorRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationVectorSearchRequest(CyreneAISchema):
    """
    应用向量检索请求
    """

    vector: list[float] = Field(min_length=1)
    top_k: int = Field(default=5, ge=1)
    filters: dict[str, Any] = Field(default_factory=dict)
    min_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationVectorSearchResult(CyreneAISchema):
    """
    应用向量检索结果
    """

    result: VectorSearchResult
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationVectorRecordResult(CyreneAISchema):
    """
    应用向量记录结果
    """

    record: VectorRecord
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationVectorWriteResult(CyreneAISchema):
    """
    应用向量写入结果
    """

    metadata: dict[str, Any] = Field(default_factory=dict)


class VectorStoreOrchestrator:
    """
    应用向量存储编排器
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._runtime = runtime

    async def upsert(
        self,
        request: ApplicationVectorUpsertRequest,
    ) -> ApplicationVectorWriteResult:
        """
        编排一次向量写入请求。
        """
        manager = self._get_vector_manager()
        await manager.upsert(request.records)
        return ApplicationVectorWriteResult(
            metadata={
                **request.metadata,
                "record_count": len(request.records),
            }
        )

    async def get(self, record_id: str) -> ApplicationVectorRecordResult:
        """
        编排一次向量读取请求。
        """
        manager = self._get_vector_manager()
        return ApplicationVectorRecordResult(record=await manager.get(record_id))

    async def search(
        self,
        request: ApplicationVectorSearchRequest,
    ) -> ApplicationVectorSearchResult:
        """
        编排一次向量检索请求。
        """
        manager = self._get_vector_manager()
        result = await manager.search(
            VectorQuery(
                vector=request.vector,
                top_k=request.top_k,
                filters=request.filters.copy(),
                min_score=request.min_score,
                metadata=request.metadata.copy(),
            )
        )
        return ApplicationVectorSearchResult(
            result=result,
            metadata={
                **request.metadata,
                "match_count": len(result.matches),
            },
        )

    async def delete(self, record_id: str) -> ApplicationVectorWriteResult:
        """
        编排一次向量删除请求。
        """
        manager = self._get_vector_manager()
        await manager.delete(record_id)
        return ApplicationVectorWriteResult(
            metadata={
                "record_id": record_id,
                "deleted": True,
            }
        )

    def _get_vector_manager(self) -> VectorManager:
        if self._runtime.vector_manager is None:
            raise StateError("Vector manager is not set")
        return self._runtime.vector_manager
