from __future__ import annotations

import asyncio

import pytest

from cyreneAI.core.context.builder import ContextWindowBuilder, map_message_source
from cyreneAI.core.errors.context import ContextBudgetError
from cyreneAI.core.schema.context import (
    ContextBudget,
    ContextBuildRequest,
    ContextItemSource,
    ContextSegmentRole,
)
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
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


class FakeTokenCounter:
    def count_message(self, message: Message) -> int:
        return sum(len(part.text or "") for part in message.content or [])

    def count_item(self, item) -> int:
        return item.token_count or 0

    def count_window(self, window) -> int:
        return 0


async def _build_without_budget():
    builder = ContextWindowBuilder()
    return await builder.build(
        ContextBuildRequest(
            session_id="session-1",
            messages=[
                _message(MessageRole.SYSTEM, "sys"),
                _message(MessageRole.USER, "hello"),
            ],
            metadata={
                "trace_id": "trace-1",
            },
        )
    )


def test_context_window_builder_keeps_all_messages_without_budget() -> None:
    result = asyncio.run(_build_without_budget())

    assert result.dropped_items == []
    assert result.window.window_id == "session-1:window"
    assert result.window.metadata == {"trace_id": "trace-1"}
    assert result.window.segments[0].segment_id == "session-1:history"
    assert result.window.segments[0].role == ContextSegmentRole.HISTORY
    assert [item.item_id for item in result.window.segments[0].items] == [
        "session-1:message:0",
        "session-1:message:1",
    ]
    assert result.window.segments[0].token_count is None


async def _build_with_budget():
    builder = ContextWindowBuilder(token_counter=FakeTokenCounter())
    return await builder.build(
        ContextBuildRequest(
            session_id="session-1",
            messages=[
                _message(MessageRole.USER, "hello"),
                _message(MessageRole.ASSISTANT, "world"),
            ],
            budget=ContextBudget(max_tokens=5),
        )
    )


def test_context_window_builder_selects_messages_within_budget() -> None:
    result = asyncio.run(_build_with_budget())

    assert [item.item_id for item in result.window.segments[0].items] == [
        "session-1:message:0",
    ]
    assert [item.item_id for item in result.dropped_items] == [
        "session-1:message:1",
    ]
    assert result.window.segments[0].token_count == 5


async def _build_with_budget_without_token_counter():
    builder = ContextWindowBuilder()
    return await builder.build(
        ContextBuildRequest(
            session_id="session-1",
            messages=[_message(MessageRole.USER, "hello")],
            budget=ContextBudget(max_tokens=5),
        )
    )


def test_context_window_builder_requires_token_counter_when_budget_is_set() -> None:
    with pytest.raises(ContextBudgetError):
        asyncio.run(_build_with_budget_without_token_counter())


def test_map_message_source_maps_roles() -> None:
    assert map_message_source(MessageRole.USER) == ContextItemSource.USER
    assert map_message_source(MessageRole.ASSISTANT) == ContextItemSource.ASSISTANT
    assert map_message_source(MessageRole.SYSTEM) == ContextItemSource.SYSTEM
    assert map_message_source(MessageRole.TOOL) == ContextItemSource.TOOL
