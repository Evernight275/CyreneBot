from __future__ import annotations


class CyreneAIError(Exception):
    """
    这里定义了与CyreneAI相关通用异常
    """

    def __init__(
        self,
        message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.cause = cause


class ConfigurationError(CyreneAIError):
    """
    当配置错误时引发此异常
    """

    pass


class RequestError(CyreneAIError):
    """
    当请求错误时引发此异常
    """

    pass


class ResponseError(CyreneAIError):
    """
    当响应错误时引发此异常
    """

    pass


class UnavailableError(CyreneAIError):
    """
    当服务不可用时引发此异常
    """

    pass


class RequestTimeoutError(UnavailableError):
    """
    当请求超时时引发此异常
    """

    pass


class RateLimitError(UnavailableError):
    """
    当请求速率限制时引发此异常
    """

    pass


class AuthorizationError(UnavailableError):
    """
    当授权错误时引发此异常
    """

    pass


class ValidationError(CyreneAIError):
    """
    当验证错误时引发此异常
    """

    pass


class NotFoundError(CyreneAIError):
    """
    当请求的资源不存在时引发此异常
    """

    pass


class ConflictError(CyreneAIError):
    """
    当请求的资源存在冲突时引发此异常
    """

    pass


class UnsupportedError(CyreneAIError):
    """
    当请求的能力不支持时引发此异常
    """

    pass


class StateError(CyreneAIError):
    """
    当请求的资源状态错误时引发此异常
    """

    pass


class DependencyError(CyreneAIError):
    """
    当请求的资源依赖项错误时引发此异常
    """

    pass
