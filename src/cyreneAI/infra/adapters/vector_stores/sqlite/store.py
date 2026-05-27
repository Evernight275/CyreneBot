from __future__ import annotations

from datetime import UTC, datetime
from math import sqrt
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from cyreneAI.core.errors.vector import (
    VectorInputError,
    VectorNotFoundError,
    VectorStoreError,
)
from cyreneAI.core.schema.vector import (
    VectorQuery,
    VectorRecord,
    VectorSearchMatch,
    VectorSearchResult,
)
from cyreneAI.core.vector.vector_protocol import VectorStoreProtocol
from cyreneAI.infra.adapters.vector_stores.sqlite.tables import vector_records


class SQLiteVectorStore(VectorStoreProtocol):
    """
    SQLite 向量存储。
    """

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        max_search_candidates: int = 10_000,
    ) -> None:
        self._engine = engine
        self._max_search_candidates = max_search_candidates

    async def upsert(self, records: list[VectorRecord]) -> None:
        """
        写入或更新向量记录。
        """
        for record in records:
            _validate_vector(record.vector, label=record.record_id)

        try:
            async with self._engine.begin() as connection:
                for record in records:
                    now = datetime.now(UTC)
                    existing = await connection.execute(
                        select(vector_records.c.record_id).where(
                            vector_records.c.record_id == record.record_id
                        )
                    )
                    existing_record_id = existing.scalar_one_or_none()
                    payload = record.model_dump(mode="json")
                    if existing_record_id is None:
                        await connection.execute(
                            insert(vector_records).values(
                                record_id=record.record_id,
                                payload=payload,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                        continue

                    await connection.execute(
                        update(vector_records)
                        .where(vector_records.c.record_id == record.record_id)
                        .values(
                            payload=payload,
                            updated_at=now,
                        )
                    )
        except SQLAlchemyError as exc:
            raise VectorStoreError("Failed to upsert vector records", cause=exc) from exc

    async def get(self, record_id: str) -> VectorRecord:
        """
        获取向量记录。
        """
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(vector_records.c.payload).where(
                        vector_records.c.record_id == record_id
                    )
                )
                payload = result.scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise VectorStoreError(
                f"Failed to get vector record {record_id}",
                cause=exc,
            ) from exc

        if payload is None:
            raise VectorNotFoundError(f"向量记录 {record_id} 不存在")
        return _map_vector_record(payload)

    async def search(self, query: VectorQuery) -> VectorSearchResult:
        """
        检索相似向量记录。
        """
        _validate_vector(query.vector, label="query")
        try:
            async with self._engine.connect() as connection:
                statement = select(vector_records.c.payload)
                if self._max_search_candidates >= 0:
                    statement = statement.limit(self._max_search_candidates + 1)
                result = await connection.execute(statement)
                payloads = result.scalars().all()
        except SQLAlchemyError as exc:
            raise VectorStoreError("Failed to search vector records", cause=exc) from exc
        if (
            self._max_search_candidates >= 0
            and len(payloads) > self._max_search_candidates
        ):
            raise VectorStoreError("Vector search exceeded maximum candidate count")

        records = [_map_vector_record(payload) for payload in payloads]
        matches: list[VectorSearchMatch] = []
        for record in records:
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
                "candidate_count": len(records),
            },
        )

    async def delete(self, record_id: str) -> None:
        """
        删除向量记录。
        """
        try:
            async with self._engine.begin() as connection:
                result = await connection.execute(
                    delete(vector_records).where(
                        vector_records.c.record_id == record_id
                    )
                )
        except SQLAlchemyError as exc:
            raise VectorStoreError(
                f"Failed to delete vector record {record_id}",
                cause=exc,
            ) from exc

        if result.rowcount == 0:
            raise VectorNotFoundError(f"向量记录 {record_id} 不存在")

    async def close(self) -> None:
        """
        关闭数据库连接池。
        """
        await self._engine.dispose()


def _map_vector_record(payload: Any) -> VectorRecord:
    try:
        return VectorRecord.model_validate(payload)
    except PydanticValidationError as exc:
        raise VectorInputError("Stored vector record payload is invalid", cause=exc) from exc


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
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right))
    return dot / (left_norm * right_norm)
