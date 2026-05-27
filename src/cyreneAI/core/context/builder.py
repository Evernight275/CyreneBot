from __future__ import annotations

from cyreneAI.core.context.context_protocol import ContextTokenCounterProtocol
from cyreneAI.core.context.policy import (
    get_available_context_tokens,
    select_context_items_within_budget,
)
from cyreneAI.core.schema.context import (
    ContextBuildRequest,
    ContextBuildResult,
    ContextItem,
    ContextItemSource,
    ContextItemType,
    ContextSegment,
    ContextSegmentRole,
    ContextWindow,
)
from cyreneAI.core.schema.message import Message, MessageRole


class ContextWindowBuilder:
    """
    上下文窗口构建器
    """

    def __init__(
        self,
        token_counter: ContextTokenCounterProtocol | None = None,
    ) -> None:
        self._token_counter = token_counter

    async def build(self, request: ContextBuildRequest) -> ContextBuildResult:
        """
        根据构建请求生成上下文窗口。
        """
        items = [
            self._build_message_item(
                session_id=request.session_id,
                index=index,
                message=message,
            )
            for index, message in enumerate(request.messages)
        ]
        available_tokens = get_available_context_tokens(request.budget)
        selected_items = select_context_items_within_budget(
            items=items,
            max_tokens=available_tokens,
        )
        selected_ids = {item.item_id for item in selected_items}
        dropped_items = [item for item in items if item.item_id not in selected_ids]

        segment = ContextSegment(
            segment_id=f"{request.session_id}:history",
            role=ContextSegmentRole.HISTORY,
            items=selected_items,
            token_count=_sum_known_token_counts(selected_items),
        )
        window = ContextWindow(
            window_id=f"{request.session_id}:window",
            segments=[segment],
            budget=request.budget,
            metadata=request.metadata.copy(),
        )
        return ContextBuildResult(
            window=window,
            dropped_items=dropped_items,
        )

    def _build_message_item(
        self,
        *,
        session_id: str,
        index: int,
        message: Message,
    ) -> ContextItem:
        token_count = (
            self._token_counter.count_message(message)
            if self._token_counter is not None
            else None
        )
        return ContextItem(
            item_id=f"{session_id}:message:{index}",
            type=ContextItemType.MESSAGE,
            source=map_message_source(message.role),
            message=message,
            token_count=token_count,
            metadata={
                "message_index": index,
            },
        )


def map_message_source(role: MessageRole) -> ContextItemSource:
    """
    将消息角色映射为上下文来源。
    """
    if role == MessageRole.USER:
        return ContextItemSource.USER
    if role == MessageRole.ASSISTANT:
        return ContextItemSource.ASSISTANT
    if role == MessageRole.SYSTEM:
        return ContextItemSource.SYSTEM
    if role == MessageRole.TOOL:
        return ContextItemSource.TOOL
    return ContextItemSource.UNKNOWN


def _sum_known_token_counts(items: list[ContextItem]) -> int | None:
    if any(item.token_count is None for item in items):
        return None
    return sum(item.token_count or 0 for item in items)
