from __future__ import annotations

import asyncio

from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.schema.context import ContextSnapshot, ContextWindow


class FakeContextStore:
    def __init__(self) -> None:
        self.snapshots: dict[str, ContextSnapshot] = {}
        self.deleted_snapshot_ids: list[str] = []

    async def save_snapshot(self, snapshot: ContextSnapshot) -> None:
        self.snapshots[snapshot.snapshot_id] = snapshot

    async def get_snapshot(self, snapshot_id: str) -> ContextSnapshot:
        return self.snapshots[snapshot_id]

    async def list_snapshots(self, session_id: str) -> list[ContextSnapshot]:
        return [
            snapshot
            for snapshot in self.snapshots.values()
            if snapshot.session_id == session_id
        ]

    async def delete_snapshot(self, snapshot_id: str) -> None:
        self.deleted_snapshot_ids.append(snapshot_id)
        self.snapshots.pop(snapshot_id, None)


def _snapshot(snapshot_id: str, session_id: str) -> ContextSnapshot:
    return ContextSnapshot(
        snapshot_id=snapshot_id,
        session_id=session_id,
        window=ContextWindow(window_id=f"{snapshot_id}:window"),
    )


async def _run_context_manager_lifecycle() -> None:
    store = FakeContextStore()
    manager = ContextManager(store)
    first = _snapshot("snapshot-1", "session-1")
    second = _snapshot("snapshot-2", "session-1")
    other = _snapshot("snapshot-3", "session-2")

    await manager.save(first)
    await manager.save(second)
    await manager.save(other)

    assert await manager.get("snapshot-1") == first
    assert await manager.list_by_session("session-1") == [first, second]

    await manager.remove("snapshot-1")

    assert store.deleted_snapshot_ids == ["snapshot-1"]
    assert await manager.list_by_session("session-1") == [second]


def test_context_manager_delegates_snapshot_lifecycle_to_store() -> None:
    asyncio.run(_run_context_manager_lifecycle())
