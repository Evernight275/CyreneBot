from __future__ import annotations

import asyncio

import pytest

from cyreneAI.application.agent.history import AgentRunHistoryReader
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.errors.base import NotFoundError, ValidationError
from cyreneAI.core.errors.context import ContextNotFoundError
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.context import (
    ContextItem,
    ContextItemSource,
    ContextItemType,
    ContextSegment,
    ContextSegmentRole,
    ContextSnapshot,
    ContextWindow,
)
from cyreneAI.core.schema.message import ContentPart, ContentPartType, Message, MessageRole


class FakeContextStore:
    def __init__(self) -> None:
        self.snapshots: list[ContextSnapshot] = []

    async def save_snapshot(self, snapshot: ContextSnapshot) -> None:
        self.snapshots.append(snapshot)

    async def get_snapshot(self, snapshot_id: str) -> ContextSnapshot:
        for snapshot in self.snapshots:
            if snapshot.snapshot_id == snapshot_id:
                return snapshot
        raise ContextNotFoundError(f"Context snapshot not found: {snapshot_id}")

    async def list_snapshots(self, session_id: str) -> list[ContextSnapshot]:
        return [
            snapshot
            for snapshot in self.snapshots
            if snapshot.session_id == session_id
        ]

    async def delete_snapshot(self, snapshot_id: str) -> None:
        self.snapshots = [
            snapshot
            for snapshot in self.snapshots
            if snapshot.snapshot_id != snapshot_id
        ]

    async def delete_snapshots_for_session(self, session_id: str) -> int:
        deleted_count = len(
            [
                snapshot
                for snapshot in self.snapshots
                if snapshot.session_id == session_id
            ]
        )
        self.snapshots = [
            snapshot
            for snapshot in self.snapshots
            if snapshot.session_id != session_id
        ]
        return deleted_count


def _runtime(store: FakeContextStore) -> CyreneAIRuntime:
    return CyreneAIRuntime(
        provider_manager=ProviderManager(ProviderFactory()),
        context_builder=ContextWindowBuilder(),
        context_manager=ContextManager(store),
    )


def _snapshot(
    snapshot_id: str,
    *,
    metadata: dict[str, object] | None = None,
    trace_items: list[ContextItem] | None = None,
    session_id: str = "session-1",
) -> ContextSnapshot:
    segments: list[ContextSegment] = []
    if trace_items is not None:
        segments.append(
            ContextSegment(
                segment_id=f"{snapshot_id}:trace",
                role=ContextSegmentRole.WORKING,
                items=trace_items,
            )
        )
    return ContextSnapshot(
        snapshot_id=snapshot_id,
        session_id=session_id,
        window=ContextWindow(
            window_id=f"{snapshot_id}:window",
            segments=segments,
        ),
        metadata=metadata or {},
    )


def _message(role: MessageRole, text: str) -> Message:
    return Message(
        role=role,
        content=[
            ContentPart(
                type=ContentPartType.TEXT,
                text=text,
            )
        ],
    )


async def _run_history_reader_lists_runs_latest_first_with_limit() -> None:
    store = FakeContextStore()
    runtime = _runtime(store)
    await store.save_snapshot(_snapshot("plain"))
    await store.save_snapshot(
        _snapshot(
            "old-run",
            metadata={"agent_loop": "minimal"},
        )
    )
    await store.save_snapshot(
        _snapshot(
            "new-run",
            metadata={
                "agent_loop": "minimal",
                "provider_id": "provider-1",
                "model": "model-1",
                "finished_at": "2026-06-04T00:00:00+00:00",
                "completed": True,
                "stop_reason": "final_response",
                "step_count": 2,
                "tool_call_count": 1,
                "tool_result_count": 1,
                "tool_error_count": 0,
                "tool_names": ["lookup"],
            },
        )
    )

    result = await AgentRunHistoryReader(runtime).list_runs("session-1", limit=2)

    assert [run.snapshot_id for run in result.runs] == ["new-run", "old-run"]
    assert result.runs[0].provider_id == "provider-1"
    assert result.runs[0].model == "model-1"
    assert result.runs[0].finished_at == "2026-06-04T00:00:00+00:00"
    assert result.runs[0].completed is True
    assert result.runs[0].tool_names == ["lookup"]
    assert result.runs[1].finished_at == "-"
    assert result.runs[1].completed is None
    assert result.runs[1].step_count == 0


def test_history_reader_lists_runs_latest_first_with_limit() -> None:
    asyncio.run(_run_history_reader_lists_runs_latest_first_with_limit())


async def _run_history_reader_get_run_returns_compact_trace_preview() -> None:
    store = FakeContextStore()
    runtime = _runtime(store)
    await store.save_snapshot(
        _snapshot(
            "trace-run",
            metadata={
                "agent_loop": "minimal",
                "completed": True,
                "stop_reason": "final_response",
            },
            trace_items=[
                ContextItem(
                    item_id="trace-tool",
                    type=ContextItemType.TOOL_TRACE,
                    source=ContextItemSource.TOOL,
                    content="lookup result\nwith extra whitespace",
                    metadata={"agent_trace_index": 0},
                ),
                ContextItem(
                    item_id="trace-final",
                    type=ContextItemType.MESSAGE,
                    source=ContextItemSource.ASSISTANT,
                    message=_message(
                        MessageRole.ASSISTANT,
                        "final answer " + ("x" * 260),
                    ),
                    metadata={"agent_trace_index": 1},
                ),
            ],
        )
    )

    result = await AgentRunHistoryReader(runtime).get_run("trace-run")

    assert result.run.snapshot_id == "trace-run"
    assert result.run.trace_item_count == 2
    assert result.run.last_assistant is not None
    assert result.run.last_assistant.startswith("final answer")
    assert len(result.run.last_assistant) <= 240
    assert [item.item_id for item in result.trace_items] == [
        "trace-tool",
        "trace-final",
    ]
    assert result.trace_items[0].text_preview == "lookup result with extra whitespace"
    assert result.trace_items[1].role == "assistant"


def test_history_reader_get_run_returns_compact_trace_preview() -> None:
    asyncio.run(_run_history_reader_get_run_returns_compact_trace_preview())


async def _run_history_reader_rejects_invalid_limit_and_missing_runs() -> None:
    store = FakeContextStore()
    runtime = _runtime(store)
    reader = AgentRunHistoryReader(runtime)
    await store.save_snapshot(_snapshot("plain"))

    with pytest.raises(ValidationError):
        await reader.list_runs("session-1", limit=0)
    with pytest.raises(NotFoundError):
        await reader.get_run("missing-run")
    with pytest.raises(NotFoundError):
        await reader.get_run("plain")
    with pytest.raises(NotFoundError):
        await reader.latest_run("session-1")


def test_history_reader_rejects_invalid_limit_and_missing_runs() -> None:
    asyncio.run(_run_history_reader_rejects_invalid_limit_and_missing_runs())
