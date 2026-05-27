from __future__ import annotations

from cyreneAI.core.errors.base import (
    CyreneAIError,
    ValidationError,
    RequestError,
    ResponseError,
)


class ChatError(CyreneAIError):
    """
    这里定义了与Chat相关通用异常
    """

    pass


class ChatInputError(ChatError, ValidationError):
    """
    当Chat输入内容不合法时引发此异常
    """

    pass


class ChatToolCallError(ChatError, ResponseError):
    """
    当Chat调用工具时引发此异常
    """

    pass


class ChatContextLengthError(
    ChatError,
    RequestError,
):
    """
    当Chat上下文长度超过限制时引发此异常
    """

    pass


class ChatStreamError(ChatError, ResponseError):
    """
    当Chat流式响应错误时引发此异常
    比如：
    1. 流式响应超时
    2. 流式响应被中断
    """

    pass
