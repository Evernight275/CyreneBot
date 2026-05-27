from __future__ import annotations

import pytest
from pydantic import ValidationError

from cyreneAI.core.schema.context import (
    ContextBudget,
    ContextBuildRequest,
    ContextBuildResult,
    ContextItem,
    ContextItemSource,
    ContextItemType,
    ContextSegment,
    ContextSegmentRole,
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


def test_context_item_can_hold_message() -> None:
    message = _message("hello")

    item = ContextItem(
        item_id="item-1",
        type=ContextItemType.MESSAGE,
        source=ContextItemSource.USER,
        message=message,
        token_count=3,
        priority=10,
        pinned=True,
    )

    assert item.message is message
    assert item.content is None
    assert item.token_count == 3
    assert item.priority == 10
    assert item.pinned is True


def test_context_window_and_snapshot_build_nested_structure() -> None:
    item = ContextItem(
        item_id="item-1",
        type=ContextItemType.MESSAGE,
        message=_message("hello"),
    )
    segment = ContextSegment(
        segment_id="segment-1",
        role=ContextSegmentRole.HISTORY,
        items=[item],
        token_count=3,
    )
    budget = ContextBudget(
        max_tokens=100,
        reserved_output_tokens=20,
        used_tokens=3,
    )
    window = ContextWindow(
        window_id="window-1",
        segments=[segment],
        budget=budget,
    )
    snapshot = ContextSnapshot(
        snapshot_id="snapshot-1",
        session_id="session-1",
        window=window,
    )

    assert snapshot.window.segments[0].items[0].item_id == "item-1"
    assert snapshot.window.budget is not None
    assert snapshot.window.budget.max_tokens == 100


def test_context_build_request_and_result_defaults_are_isolated() -> None:
    first_request = ContextBuildRequest(session_id="session-1")
    second_request = ContextBuildRequest(session_id="session-2")

    first_request.messages.append(_message("hello"))
    first_request.metadata["key"] = "value"

    assert second_request.messages == []
    assert second_request.metadata == {}

    result = ContextBuildResult(window=ContextWindow(window_id="window-1"))
    result.dropped_items.append(
        ContextItem(
            item_id="dropped-1",
            type=ContextItemType.SUMMARY,
        )
    )

    another_result = ContextBuildResult(window=ContextWindow(window_id="window-2"))
    assert another_result.dropped_items == []


def test_context_token_counts_must_be_non_negative() -> None:
    with pytest.raises(ValidationError):
        ContextBudget(max_tokens=-1)

    with pytest.raises(ValidationError):
        ContextItem(
            item_id="item-1",
            type=ContextItemType.MESSAGE,
            token_count=-1,
        )

    with pytest.raises(ValidationError):
        ContextSegment(
            segment_id="segment-1",
            role=ContextSegmentRole.HISTORY,
            token_count=-1,
        )
