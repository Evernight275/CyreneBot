from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.message import ContentPart


class BotBase(CyreneAISchema):
    """
    所有与 bot 内核有关的 schema 应该继承这个 schema。
    """

    pass


class BotEventType(StrEnum):
    """
    标准化 bot 事件类型。
    """

    MESSAGE = "message"
    COMMAND = "command"
    MEMBER_JOINED = "member_joined"
    MEMBER_LEFT = "member_left"
    UNKNOWN = "unknown"


class BotActionType(StrEnum):
    """
    标准化 bot 动作类型。
    """

    SEND_MESSAGE = "send_message"
    NOOP = "noop"


class BotSessionStatus(StrEnum):
    """
    bot 会话状态。
    """

    ACTIVE = "active"
    CLOSED = "closed"


class BotMessage(BotBase):
    """
    channel 无关的 bot 消息。
    """

    message_id: str | None = None
    sender_id: str | None = None
    content: list[ContentPart] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BotSession(BotBase):
    """
    channel 无关的 bot 会话引用。
    """

    session_id: str
    channel_id: str
    user_id: str | None = None
    thread_id: str | None = None
    status: BotSessionStatus = BotSessionStatus.ACTIVE
    metadata: dict[str, Any] = Field(default_factory=dict)


class BotConversationState(BotBase):
    """
    bot 会话状态快照。
    """

    session: BotSession
    turn_count: int = Field(default=0, ge=0)
    last_event_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BotSessionUpdate(BotBase):
    """
    bot 会话更新请求。
    """

    session_id: str
    status: BotSessionStatus | None = None
    last_event_id: str | None = None
    increment_turn_count: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class BotChannelDefinition(BotBase):
    """
    channel adapter 注册定义。
    """

    channel_id: str
    name: str
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BotEvent(BotBase):
    """
    channel adapter 输入给 bot 内核的标准化事件。
    """

    event_id: str
    event_type: BotEventType
    channel_id: str
    session_id: str
    user_id: str | None = None
    thread_id: str | None = None
    message: BotMessage | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BotAction(BotBase):
    """
    bot 内核输出给 channel adapter 的标准化动作。
    """

    action_type: BotActionType
    channel_id: str
    session_id: str
    recipient_id: str | None = None
    thread_id: str | None = None
    message: BotMessage | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
