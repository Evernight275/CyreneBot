from __future__ import annotations

from typing import cast

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.errors.base import NotFoundError, StateError, ValidationError
from cyreneAI.core.schema.agent import (
    AgentRunHistoryItem,
    AgentRunHistoryListResult,
    AgentRunTraceItem,
    AgentRunTraceResult,
)
from cyreneAI.core.schema.context import ContextItem, ContextItemType, ContextSnapshot
from cyreneAI.core.schema.message import ContentPart, ContentPartType, MessageRole

DEFAULT_AGENT_RUN_HISTORY_LIMIT = 10
MAX_AGENT_RUN_HISTORY_LIMIT = 50
TRACE_TEXT_PREVIEW_CHARS = 240


class AgentRunHistoryReader:
    """
    从 context snapshots 读取 Agent run 历史。
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._runtime = runtime

    async def list_runs(
        self,
        session_id: str,
        *,
        limit: int = DEFAULT_AGENT_RUN_HISTORY_LIMIT,
    ) -> AgentRunHistoryListResult:
        limit = _validate_limit(limit)
        manager = self._context_manager()
        snapshots = await manager.list_by_session(session_id)
        runs = [
            _history_item_from_snapshot(snapshot)
            for snapshot in reversed(snapshots)
            if _is_agent_run_snapshot(snapshot)
        ][:limit]
        return AgentRunHistoryListResult(
            session_id=session_id,
            limit=limit,
            runs=runs,
        )

    async def get_run(self, snapshot_id: str) -> AgentRunTraceResult:
        manager = self._context_manager()
        try:
            snapshot = await manager.get(snapshot_id)
        except NotFoundError as exc:
            raise NotFoundError(f"Agent run not found: {snapshot_id}") from exc
        if not _is_agent_run_snapshot(snapshot):
            raise NotFoundError(f"Agent run not found: {snapshot_id}")
        return _trace_result_from_snapshot(snapshot)

    async def latest_run(self, session_id: str) -> AgentRunTraceResult:
        result = await self.list_runs(session_id, limit=1)
        if not result.runs:
            raise NotFoundError(f"Agent run not found for session: {session_id}")
        return await self.get_run(result.runs[0].snapshot_id)

    def _context_manager(self) -> ContextManager:
        manager = self._runtime.context_manager
        if manager is None:
            raise StateError("Context manager is not configured.")
        return manager


def _validate_limit(limit: int) -> int:
    if limit < 1 or limit > MAX_AGENT_RUN_HISTORY_LIMIT:
        raise ValidationError(
            f"Agent run history limit must be between 1 and {MAX_AGENT_RUN_HISTORY_LIMIT}."
        )
    return limit


def _trace_result_from_snapshot(snapshot: ContextSnapshot) -> AgentRunTraceResult:
    trace_items = _agent_trace_items(snapshot)
    return AgentRunTraceResult(
        run=_history_item_from_snapshot(snapshot),
        trace_items=[
            _trace_item_from_context_item(item, fallback_index=index)
            for index, item in enumerate(trace_items)
        ],
        metadata=dict(snapshot.metadata),
    )


def _history_item_from_snapshot(snapshot: ContextSnapshot) -> AgentRunHistoryItem:
    metadata = snapshot.metadata
    trace_items = _agent_trace_items(snapshot)
    return AgentRunHistoryItem(
        snapshot_id=snapshot.snapshot_id,
        session_id=snapshot.session_id,
        provider_id=_metadata_str(metadata.get("provider_id"), default="-"),
        model=_metadata_str(metadata.get("model"), default="-"),
        finished_at=_metadata_str(metadata.get("finished_at"), default="-"),
        completed=_metadata_bool(metadata.get("completed")),
        stop_reason=_metadata_str(metadata.get("stop_reason"), default="-"),
        step_count=_metadata_int(metadata.get("step_count")),
        tool_call_count=_metadata_int(metadata.get("tool_call_count")),
        tool_result_count=_metadata_int(metadata.get("tool_result_count")),
        tool_error_count=_metadata_int(metadata.get("tool_error_count")),
        tool_names=_metadata_strings(metadata.get("tool_names")),
        trace_item_count=len(trace_items),
        last_assistant=_last_assistant_trace_text(trace_items),
    )


def _trace_item_from_context_item(
    item: ContextItem,
    *,
    fallback_index: int,
) -> AgentRunTraceItem:
    message = item.message
    text = item.content or _message_text(
        message.content if message is not None else None
    )
    return AgentRunTraceItem(
        index=_metadata_int(
            item.metadata.get("agent_trace_index"), fallback=fallback_index
        ),
        item_id=item.item_id,
        item_type=item.type.value,
        source=item.source.value,
        role=message.role.value if message is not None else None,
        name=message.name if message is not None else None,
        tool_call_id=message.tool_call_id if message is not None else None,
        text_preview=_truncate_line(text, TRACE_TEXT_PREVIEW_CHARS) if text else None,
        metadata=dict(item.metadata),
    )


def _is_agent_run_snapshot(snapshot: ContextSnapshot) -> bool:
    if snapshot.metadata.get("agent_loop") == "minimal":
        return True
    return bool(_agent_trace_items(snapshot))


def _agent_trace_items(snapshot: ContextSnapshot) -> list[ContextItem]:
    return [
        item
        for segment in snapshot.window.segments
        for item in segment.items
        if (
            item.type == ContextItemType.TOOL_TRACE
            or "agent_trace_index" in item.metadata
        )
    ]


def _last_assistant_trace_text(items: list[ContextItem]) -> str | None:
    for item in reversed(items):
        message = item.message
        if message is None or message.role != MessageRole.ASSISTANT:
            continue
        text = _message_text(message.content)
        if text:
            return _truncate_line(text, TRACE_TEXT_PREVIEW_CHARS)
    return None


def _message_text(content: list[ContentPart] | None) -> str:
    if not content:
        return ""
    return "".join(
        part.text or "" for part in content if part.type == ContentPartType.TEXT
    )


def _metadata_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _metadata_int(value: object, *, fallback: int = 0) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return fallback


def _metadata_str(value: object, *, default: str) -> str:
    if isinstance(value, str) and value:
        return value
    return default


def _metadata_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [item for item in items if isinstance(item, str) and item]


def _truncate_line(text: str, max_chars: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    if max_chars <= 3:
        return normalized[:max_chars]
    return f"{normalized[: max_chars - 3]}..."


__all__ = [
    "AgentRunHistoryReader",
    "DEFAULT_AGENT_RUN_HISTORY_LIMIT",
    "MAX_AGENT_RUN_HISTORY_LIMIT",
]
