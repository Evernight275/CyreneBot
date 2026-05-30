from __future__ import annotations

from cyreneAI.core.errors.base import (
    ConfigurationError,
    CyreneAIError,
    NotFoundError,
    RequestError,
    ResponseError,
    StateError,
    ValidationError,
)


class ToolError(CyreneAIError):
    """
    这里定义了与工具调用相关的通用异常
    """

    pass


class ToolInputError(ToolError, ValidationError):
    """
    当工具输入不合法时引发此异常
    """

    pass


class ToolNotFoundError(ToolError, NotFoundError):
    """
    当请求的工具不存在时引发此异常
    """

    pass


class ToolConfigurationError(ToolError, ConfigurationError):
    """
    当工具配置错误时引发此异常
    """

    pass


class ToolExecutionError(ToolError, RequestError):
    """
    当工具执行失败时引发此异常
    """

    pass


class ToolPolicyError(ToolExecutionError):
    """
    当工具执行策略拒绝调用时引发此异常
    """

    pass


class ToolResultError(ToolError, ResponseError):
    """
    当工具执行结果不可用时引发此异常
    """

    pass


class ToolStateError(ToolError, StateError):
    """
    当工具状态不合法时引发此异常
    """

    pass
