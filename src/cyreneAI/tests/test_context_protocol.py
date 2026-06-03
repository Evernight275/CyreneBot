from __future__ import annotations

import asyncio
from pathlib import Path

from cyreneAI.core.context.context_protocol import (
    ContextBuilderProtocol,
    ContextCompressorProtocol,
    ContextRetrieverProtocol,
    ContextStoreProtocol,
    ContextTokenCounterProtocol,
)
from cyreneAI.core.schema.context import (
    ContextBuildRequest,
    ContextBuildResult,
    ContextItem,
    ContextItemType,
    ContextSnapshot,
    ContextWindow,
)
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)


def _message(text: str) -> Message:
    return Message(
        role=MessageRole.USER,
        content=[
            ContentPart(
                type=ContentPartType.TEXT,
                text=text,
            )
        ],
    )


def _item(item_id: str, text: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        type=ContextItemType.MESSAGE,
        content=text,
        token_count=len(text),
    )


class FakeContextStore:
    def __init__(self) -> None:
        self._snapshots: dict[str, ContextSnapshot] = {}

    async def save_snapshot(self, snapshot: ContextSnapshot) -> None:
        self._snapshots[snapshot.snapshot_id] = snapshot

    async def get_snapshot(self, snapshot_id: str) -> ContextSnapshot:
        return self._snapshots[snapshot_id]

    async def list_snapshots(self, session_id: str) -> list[ContextSnapshot]:
        return [
            snapshot
            for snapshot in self._snapshots.values()
            if snapshot.session_id == session_id
        ]

    async def delete_snapshot(self, snapshot_id: str) -> None:
        self._snapshots.pop(snapshot_id, None)

    async def delete_snapshots_for_session(self, session_id: str) -> int:
        snapshot_ids = [
            snapshot.snapshot_id
            for snapshot in self._snapshots.values()
            if snapshot.session_id == session_id
        ]
        for snapshot_id in snapshot_ids:
            self._snapshots.pop(snapshot_id, None)
        return len(snapshot_ids)


class FakeContextBuilder:
    async def build(self, request: ContextBuildRequest) -> ContextBuildResult:
        return ContextBuildResult(
            window=ContextWindow(
                window_id=f"{request.session_id}-window",
            )
        )


class FakeContextCompressor:
    async def compress(self, items, budget=None) -> ContextItem:
        text = "\n".join(item.content or "" for item in items)
        return ContextItem(
            item_id="summary-1",
            type=ContextItemType.SUMMARY,
            content=text,
        )


class FakeContextRetriever:
    async def retrieve(
        self,
        *,
        session_id: str,
        query: str | None = None,
        limit: int | None = None,
        metadata: dict | None = None,
    ) -> list[ContextItem]:
        items = [_item("item-1", query or session_id)]
        return items[:limit] if limit is not None else items


class FakeTokenCounter:
    def count_message(self, message: Message) -> int:
        return sum(len(part.text or "") for part in message.content or [])

    def count_item(self, item: ContextItem) -> int:
        return item.token_count or len(item.content or "")

    def count_window(self, window: ContextWindow) -> int:
        return sum(
            item.token_count or 0
            for segment in window.segments
            for item in segment.items
        )


async def _use_store(store: ContextStoreProtocol) -> None:
    snapshot = ContextSnapshot(
        snapshot_id="snapshot-1",
        session_id="session-1",
        window=ContextWindow(window_id="window-1"),
    )

    await store.save_snapshot(snapshot)

    assert await store.get_snapshot("snapshot-1") == snapshot
    assert await store.list_snapshots("session-1") == [snapshot]

    await store.delete_snapshot("snapshot-1")
    assert await store.list_snapshots("session-1") == []

    await store.save_snapshot(snapshot)
    assert await store.delete_snapshots_for_session("session-1") == 1
    assert await store.list_snapshots("session-1") == []


async def _use_builder(builder: ContextBuilderProtocol) -> None:
    result = await builder.build(ContextBuildRequest(session_id="session-1"))

    assert result.window.window_id == "session-1-window"


async def _use_compressor(compressor: ContextCompressorProtocol) -> None:
    item = await compressor.compress([_item("item-1", "hello")])

    assert item.type == ContextItemType.SUMMARY
    assert item.content == "hello"


async def _use_retriever(retriever: ContextRetrieverProtocol) -> None:
    items = await retriever.retrieve(
        session_id="session-1",
        query="hello",
        limit=1,
    )

    assert items[0].content == "hello"


def _use_token_counter(counter: ContextTokenCounterProtocol) -> None:
    assert counter.count_message(_message("hello")) == 5
    assert counter.count_item(_item("item-1", "hello")) == 5
    assert counter.count_window(ContextWindow(window_id="window-1")) == 0


def test_context_protocols_can_be_implemented_by_fakes() -> None:
    asyncio.run(_use_store(FakeContextStore()))
    asyncio.run(_use_builder(FakeContextBuilder()))
    asyncio.run(_use_compressor(FakeContextCompressor()))
    asyncio.run(_use_retriever(FakeContextRetriever()))
    _use_token_counter(FakeTokenCounter())


def test_core_context_does_not_import_infra_or_external_sdks() -> None:
    context_dir = Path(__file__).parents[1] / "core" / "context"
    forbidden_patterns = [
        "cyreneAI.infra",
        "openai",
        "anthropic",
        "google.genai",
        "httpx",
        "dotenv",
        "os.getenv",
    ]

    for path in context_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            assert pattern not in text
