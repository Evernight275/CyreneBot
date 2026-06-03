from __future__ import annotations

from cyreneAI.core.context.context_protocol import ContextStoreProtocol
from cyreneAI.core.schema.context import ContextSnapshot


class ContextManager:
    """
    上下文快照生命周期管理器
    """

    def __init__(self, store: ContextStoreProtocol) -> None:
        self._store = store

    async def save(self, snapshot: ContextSnapshot) -> None:
        """
        保存上下文快照
        """
        await self._store.save_snapshot(snapshot)

    async def get(self, snapshot_id: str) -> ContextSnapshot:
        """
        获取上下文快照
        """
        return await self._store.get_snapshot(snapshot_id)

    async def list_by_session(self, session_id: str) -> list[ContextSnapshot]:
        """
        列出指定会话的上下文快照
        """
        return await self._store.list_snapshots(session_id)

    async def remove(self, snapshot_id: str) -> None:
        """
        删除上下文快照
        """
        await self._store.delete_snapshot(snapshot_id)

    async def clear_session(self, session_id: str) -> int:
        """
        清空指定会话的上下文快照。
        """
        return await self._store.delete_snapshots_for_session(session_id)

    async def close(self) -> None:
        """
        关闭上下文存储
        """
        close = getattr(self._store, "close", None)
        if close is not None:
            await close()
