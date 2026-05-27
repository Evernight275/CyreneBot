from __future__ import annotations

from typing import Protocol

from cyreneAI.core.schema.vector import (
    VectorQuery,
    VectorRecord,
    VectorSearchResult,
)


class VectorStoreProtocol(Protocol):
    """
    向量存储协议
    """

    async def upsert(self, records: list[VectorRecord]) -> None:
        """
        写入或更新向量记录
        """
        ...

    async def get(self, record_id: str) -> VectorRecord:
        """
        获取向量记录
        """
        ...

    async def search(self, query: VectorQuery) -> VectorSearchResult:
        """
        检索相似向量记录
        """
        ...

    async def delete(self, record_id: str) -> None:
        """
        删除向量记录
        """
        ...
