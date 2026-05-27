from __future__ import annotations

from cyreneAI.core.errors.context import ContextBudgetError
from cyreneAI.core.schema.context import ContextBudget, ContextItem


def get_available_context_tokens(budget: ContextBudget | None) -> int | None:
    """
    获取当前上下文预算中仍可使用的 token 数。
    """
    if budget is None or budget.max_tokens is None:
        return None

    reserved_output_tokens = budget.reserved_output_tokens or 0
    used_tokens = budget.used_tokens or 0
    available = budget.max_tokens - reserved_output_tokens - used_tokens
    return max(available, 0)


def require_item_token_count(item: ContextItem) -> int:
    """
    获取上下文条目的 token 数，缺失时视为预算信息不完整。
    """
    if item.token_count is None:
        raise ContextBudgetError(f"Context item {item.item_id} missing token_count")
    return item.token_count


def calculate_items_token_count(items: list[ContextItem]) -> int:
    """
    计算上下文条目 token 总数。
    """
    return sum(require_item_token_count(item) for item in items)


def sort_context_items_for_retention(items: list[ContextItem]) -> list[ContextItem]:
    """
    按保留优先级排序上下文条目。
    """
    return sorted(
        items,
        key=lambda item: (
            not item.pinned,
            -item.priority,
        ),
    )


def select_context_items_within_budget(
    items: list[ContextItem],
    max_tokens: int | None,
) -> list[ContextItem]:
    """
    按保留优先级选择不超过预算的上下文条目。
    """
    if max_tokens is None:
        return list(items)

    selected: list[ContextItem] = []
    used_tokens = 0
    for item in sort_context_items_for_retention(items):
        item_tokens = require_item_token_count(item)
        if used_tokens + item_tokens > max_tokens:
            continue
        selected.append(item)
        used_tokens += item_tokens
    return selected
