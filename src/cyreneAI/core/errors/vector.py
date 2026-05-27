from __future__ import annotations

from cyreneAI.core.errors.base import (
    CyreneAIError,
    DependencyError,
    NotFoundError,
    ValidationError,
)


class VectorError(CyreneAIError):
    """
    这里定义了与向量存储相关的通用异常
    """

    pass


class VectorInputError(VectorError, ValidationError):
    """
    当向量输入不合法时引发此异常
    """

    pass


class VectorNotFoundError(VectorError, NotFoundError):
    """
    当请求的向量记录不存在时引发此异常
    """

    pass


class VectorStoreError(VectorError, DependencyError):
    """
    当向量存储依赖失败时引发此异常
    """

    pass
