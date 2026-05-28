from __future__ import annotations

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import StateError
from cyreneAI.core.schema.application import (
    ApplicationVectorRecordResult,
    ApplicationVectorSearchRequest,
    ApplicationVectorSearchResult,
    ApplicationVectorUpsertRequest,
    ApplicationVectorWriteResult,
)
from cyreneAI.core.schema.vector import (
    VectorQuery,
)
from cyreneAI.core.vector.manager import VectorManager


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
