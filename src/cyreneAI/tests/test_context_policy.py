from __future__ import annotations

import pytest

from cyreneAI.core.context.policy import (
    calculate_items_token_count,
    get_available_context_tokens,
    select_context_items_within_budget,
    sort_context_items_for_retention,
)
from cyreneAI.core.errors.context import ContextBudgetError
from cyreneAI.core.schema.context import ContextBudget, ContextItem, ContextItemType


def _item(
    item_id: str,
    *,
    token_count: int | None,
    priority: int = 0,
    pinned: bool = False,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        type=ContextItemType.MESSAGE,
        token_count=token_count,
        priority=priority,
        pinned=pinned,
    )


def test_get_available_context_tokens_handles_missing_and_exhausted_budget() -> None:
    assert get_available_context_tokens(None) is None
    assert get_available_context_tokens(ContextBudget()) is None
    assert (
        get_available_context_tokens(
            ContextBudget(
                max_tokens=100,
                reserved_output_tokens=20,
                used_tokens=30,
            )
        )
        == 50
    )
    assert (
        get_available_context_tokens(
            ContextBudget(
                max_tokens=100,
                reserved_output_tokens=80,
                used_tokens=50,
            )
        )
        == 0
    )


def test_calculate_items_token_count_requires_complete_token_counts() -> None:
    assert (
        calculate_items_token_count(
            [
                _item("item-1", token_count=3),
                _item("item-2", token_count=4),
            ]
        )
        == 7
    )

    with pytest.raises(ContextBudgetError):
        calculate_items_token_count([_item("item-1", token_count=None)])


def test_sort_context_items_for_retention_prefers_pinned_then_priority() -> None:
    items = [
        _item("low", token_count=1, priority=0),
        _item("high", token_count=1, priority=10),
        _item("pinned-low", token_count=1, priority=0, pinned=True),
        _item("pinned-high", token_count=1, priority=10, pinned=True),
    ]

    sorted_items = sort_context_items_for_retention(items)

    assert [item.item_id for item in sorted_items] == [
        "pinned-high",
        "pinned-low",
        "high",
        "low",
    ]


def test_select_context_items_within_budget_uses_retention_order() -> None:
    items = [
        _item("low", token_count=5, priority=0),
        _item("high", token_count=4, priority=10),
        _item("pinned", token_count=3, priority=0, pinned=True),
    ]

    selected_items = select_context_items_within_budget(items, max_tokens=7)

    assert [item.item_id for item in selected_items] == ["pinned", "high"]


def test_select_context_items_within_budget_returns_all_without_budget() -> None:
    items = [
        _item("item-1", token_count=None),
        _item("item-2", token_count=2),
    ]

    assert select_context_items_within_budget(items, max_tokens=None) == items
