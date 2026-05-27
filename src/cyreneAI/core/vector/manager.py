from __future__ import annotations

from cyreneAI.core.schema.vector import (
    VectorQuery,
    VectorRecord,
    VectorSearchResult,
)
from cyreneAI.core.vector.vector_protocol import VectorStoreProtocol


class VectorManager:
    """
    向量记录生命周期管理器
    """

    def __init__(self, store: VectorStoreProtocol) -> None:
        self._store = store

    async def upsert(self, records: list[VectorRecord]) -> None:
        """
        写入或更新向量记录
        """
        await self._store.upsert(records)

    async def get(self, record_id: str) -> VectorRecord:
        """
        获取向量记录
        """
        return await self._store.get(record_id)

    async def search(self, query: VectorQuery) -> VectorSearchResult:
        """
        检索相似向量记录
        """
        return await self._store.search(query)

    async def delete(self, record_id: str) -> None:
        """
        删除向量记录
        """
        await self._store.delete(record_id)

    async def close(self) -> None:
        """
        关闭向量存储
        """
        close = getattr(self._store, "close", None)
        if close is not None:
            await close()
