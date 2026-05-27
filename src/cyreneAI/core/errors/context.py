from __future__ import annotations

from cyreneAI.core.errors.base import (
    CyreneAIError,
    DependencyError,
    NotFoundError,
    RequestError,
    ResponseError,
    StateError,
    UnsupportedError,
    ValidationError,
)


class ContextError(CyreneAIError):
    """
    这里定义了与上下文管理相关的通用异常
    """

    pass


class ContextInputError(ContextError, ValidationError):
    """
    当上下文输入内容不合法时引发此异常
    """

    pass


class ContextNotFoundError(ContextError, NotFoundError):
    """
    当请求的上下文不存在时引发此异常
    """

    pass


class ContextStateError(ContextError, StateError):
    """
    当上下文状态不合法时引发此异常
    """

    pass


class ContextBudgetError(ContextError, RequestError):
    """
    当上下文预算不满足请求时引发此异常
    """

    pass


class ContextWindowError(ContextError, RequestError):
    """
    当上下文窗口无法按规则构建时引发此异常
    """

    pass


class ContextCompressionError(ContextError, ResponseError):
    """
    当上下文压缩失败或压缩结果不可用时引发此异常
    """

    pass


class ContextRetrievalError(ContextError, ResponseError):
    """
    当上下文检索失败或检索结果不可用时引发此异常
    """

    pass


class ContextStoreError(ContextError, DependencyError):
    """
    当上下文存储依赖失败时引发此异常
    """

    pass


class ContextUnsupportedError(ContextError, UnsupportedError):
    """
    当请求的上下文能力不受支持时引发此异常
    """

    pass
