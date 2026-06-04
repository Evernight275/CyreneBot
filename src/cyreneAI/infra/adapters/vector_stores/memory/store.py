from __future__ import annotations

from math import sqrt
from typing import Any

from cyreneAI.core.errors.vector import VectorInputError, VectorNotFoundError
from cyreneAI.core.schema.vector import (
    VectorQuery,
    VectorRecord,
    VectorSearchMatch,
    VectorSearchResult,
)
from cyreneAI.core.vector.vector_protocol import VectorStoreProtocol


class InMemoryVectorStore(VectorStoreProtocol):
    """
    内存向量存储
    """

    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}

    async def upsert(self, records: list[VectorRecord]) -> None:
        """
        写入或更新向量记录
        """
        for record in records:
            _validate_vector(record.vector, label=record.record_id)
            self._records[record.record_id] = record

    async def get(self, record_id: str) -> VectorRecord:
        """
        获取向量记录
        """
        record = self._records.get(record_id)
        if record is None:
            raise VectorNotFoundError(f"向量记录 {record_id} 不存在")
        return record

    async def search(self, query: VectorQuery) -> VectorSearchResult:
        """
        检索相似向量记录
        """
        _validate_vector(query.vector, label="query")
        matches: list[VectorSearchMatch] = []

        for record in self._records.values():
            if not _metadata_matches(record.metadata, query.filters):
                continue
            if len(record.vector) != len(query.vector):
                continue

            score = _cosine_similarity(query.vector, record.vector)
            if query.min_score is not None and score < query.min_score:
                continue
            matches.append(
                VectorSearchMatch(
                    record=record,
                    score=score,
                )
            )

        matches.sort(key=lambda match: match.score, reverse=True)
        return VectorSearchResult(
            matches=matches[: query.top_k],
            metadata={
                **query.metadata,
                "candidate_count": len(self._records),
            },
        )

    async def delete(self, record_id: str) -> None:
        """
        删除向量记录
        """
        if record_id not in self._records:
            raise VectorNotFoundError(f"向量记录 {record_id} 不存在")
        del self._records[record_id]

    async def close(self) -> None:
        """
        关闭内存向量存储
        """
        self._records.clear()


def _validate_vector(vector: list[float], *, label: str) -> None:
    if not vector:
        raise VectorInputError(f"Vector {label} cannot be empty")
    norm = sqrt(sum(value * value for value in vector))
    if norm == 0:
        raise VectorInputError(f"Vector {label} cannot be zero")


def _metadata_matches(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
    return all(metadata.get(key) == value for key, value in filters.items())


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise VectorInputError("Vector cannot be zero")
    dot = sum(
        left_value * right_value
        for left_value, right_value in zip(left, right, strict=True)
    )
    return dot / (left_norm * right_norm)
