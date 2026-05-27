from __future__ import annotations
from enum import StrEnum

from cyreneAI.core.schema.base import CyreneAISchema


class MessageRole(StrEnum):
    """
    消息角色
    """

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ContentPartType(StrEnum):
    """
    内容部分类型
    """

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    EMBED = "embed"
    LINK = "link"
    TABLE = "table"
    CODE = "code"
    FUNCTION_CALL = "function_call"


class ContentPart(CyreneAISchema):
    """
    内容部分schema
    """

    type: ContentPartType
    text: str | None = None


class Message(CyreneAISchema):
    """
    消息schema
    """

    role: MessageRole
    content: list[ContentPart] | None = None
    name: str | None = None
    tool_call_id: str | None = None
