from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.message import Message


class ContextBase(CyreneAISchema):
    """
    所有与上下文管理有关的schema应该继承这个schema
    """

    pass


class ContextItemType(StrEnum):
    """
    上下文条目类型
    """

    MESSAGE = "message"
    SUMMARY = "summary"
    MEMORY = "memory"
    TOOL_TRACE = "tool_trace"
    SYSTEM = "system"
    RETRIEVED = "retrieved"
    FILE = "file"
    CUSTOM = "custom"


class ContextItemSource(StrEnum):
    """
    上下文条目来源
    """

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
    MEMORY = "memory"
    RETRIEVER = "retriever"
    COMPRESSOR = "compressor"
    APPLICATION = "application"
    UNKNOWN = "unknown"


class ContextSegmentRole(StrEnum):
    """
    上下文片段角色
    """

    SYSTEM = "system"
    HISTORY = "history"
    MEMORY = "memory"
    RETRIEVED = "retrieved"
    TOOL_TRACE = "tool_trace"
    WORKING = "working"
    CUSTOM = "custom"


class ContextBudget(ContextBase):
    """
    上下文预算schema
    """

    max_tokens: int | None = Field(default=None, ge=0)
    reserved_output_tokens: int | None = Field(default=None, ge=0)
    used_tokens: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextItem(ContextBase):
    """
    上下文条目schema
    """

    item_id: str
    type: ContextItemType
    source: ContextItemSource = ContextItemSource.UNKNOWN
    content: str | None = None
    message: Message | None = None
    token_count: int | None = Field(default=None, ge=0)
    priority: int = Field(default=0)
    pinned: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextSegment(ContextBase):
    """
    上下文片段schema
    """

    segment_id: str
    role: ContextSegmentRole
    items: list[ContextItem] = Field(default_factory=list)
    token_count: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextWindow(ContextBase):
    """
    上下文窗口schema
    """

    window_id: str
    segments: list[ContextSegment] = Field(default_factory=list)
    budget: ContextBudget | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextSnapshot(ContextBase):
    """
    上下文快照schema
    """

    snapshot_id: str
    session_id: str
    window: ContextWindow
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextBuildRequest(ContextBase):
    """
    上下文构建请求schema
    """

    session_id: str
    messages: list[Message] = Field(default_factory=list)
    budget: ContextBudget | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextBuildResult(ContextBase):
    """
    上下文构建结果schema
    """

    window: ContextWindow
    dropped_items: list[ContextItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
