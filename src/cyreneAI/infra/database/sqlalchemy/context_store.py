from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from cyreneAI.core.context.context_protocol import ContextStoreProtocol
from cyreneAI.core.errors.context import (
    ContextInputError,
    ContextNotFoundError,
    ContextStoreError,
)
from cyreneAI.core.schema.context import ContextSnapshot
from cyreneAI.infra.database.sqlalchemy.context_tables import context_snapshots


class SQLAlchemyContextStore(ContextStoreProtocol):
    """
    SQLAlchemy 上下文存储
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save_snapshot(self, snapshot: ContextSnapshot) -> None:
        """
        保存上下文快照
        """
        now = datetime.now(UTC)
        payload = snapshot.model_dump(mode="json")

        try:
            async with self._engine.begin() as connection:
                result = await connection.execute(
                    select(context_snapshots.c.snapshot_id).where(
                        context_snapshots.c.snapshot_id == snapshot.snapshot_id
                    )
                )
                existing_snapshot_id = result.scalar_one_or_none()

                if existing_snapshot_id is None:
                    await connection.execute(
                        insert(context_snapshots).values(
                            snapshot_id=snapshot.snapshot_id,
                            session_id=snapshot.session_id,
                            payload=payload,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    return

                await connection.execute(
                    update(context_snapshots)
                    .where(context_snapshots.c.snapshot_id == snapshot.snapshot_id)
                    .values(
                        session_id=snapshot.session_id,
                        payload=payload,
                        updated_at=now,
                    )
                )
        except SQLAlchemyError as exc:
            raise ContextStoreError(
                f"Failed to save context snapshot {snapshot.snapshot_id}",
                cause=exc,
            ) from exc

    async def get_snapshot(self, snapshot_id: str) -> ContextSnapshot:
        """
        获取上下文快照
        """
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(context_snapshots.c.payload).where(
                        context_snapshots.c.snapshot_id == snapshot_id
                    )
                )
                payload = result.scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise ContextStoreError(
                f"Failed to get context snapshot {snapshot_id}",
                cause=exc,
            ) from exc

        if payload is None:
            raise ContextNotFoundError(f"上下文快照 {snapshot_id} 不存在")
        return _map_context_snapshot(payload)

    async def list_snapshots(self, session_id: str) -> list[ContextSnapshot]:
        """
        列出指定会话的上下文快照
        """
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(context_snapshots.c.payload)
                    .where(context_snapshots.c.session_id == session_id)
                    .order_by(
                        context_snapshots.c.created_at.asc(),
                        context_snapshots.c.snapshot_id.asc(),
                    )
                )
                payloads = result.scalars().all()
        except SQLAlchemyError as exc:
            raise ContextStoreError(
                f"Failed to list context snapshots for session {session_id}",
                cause=exc,
            ) from exc

        return [_map_context_snapshot(payload) for payload in payloads]

    async def delete_snapshot(self, snapshot_id: str) -> None:
        """
        删除上下文快照
        """
        try:
            async with self._engine.begin() as connection:
                await connection.execute(
                    delete(context_snapshots).where(
                        context_snapshots.c.snapshot_id == snapshot_id
                    )
                )
        except SQLAlchemyError as exc:
            raise ContextStoreError(
                f"Failed to delete context snapshot {snapshot_id}",
                cause=exc,
            ) from exc

    async def close(self) -> None:
        """
        关闭数据库连接池
        """
        await self._engine.dispose()


def _map_context_snapshot(payload: Any) -> ContextSnapshot:
    try:
        return ContextSnapshot.model_validate(payload)
    except PydanticValidationError as exc:
        raise ContextInputError(
            "Stored context snapshot payload is invalid",
            cause=exc,
        ) from exc
