from __future__ import annotations


from cyreneAI.core.errors.base import (
    CyreneAIError,
    AuthorizationError,
    ConfigurationError,
    RequestError,
    ResponseError,
    UnavailableError,
    RequestTimeoutError,
    RateLimitError,
)


class ProviderError(CyreneAIError):
    """
    这里定义了与Provider相关通用异常
    """

    pass


class ProviderNotFoundError(ProviderError):
    """
    当请求的Provider不存在时引发此异常
    """

    pass


class ProviderConfigurationError(ProviderError, ConfigurationError):
    """
    当Provider配置错误时引发此异常
    """

    pass


class ProviderRequestError(ProviderError, RequestError):
    """
    当Provider请求错误时引发此异常
    """

    pass


class ProviderResponseError(ProviderError, ResponseError):
    """
    当Provider响应错误时引发此异常
    """

    pass


class ProviderUnavailableError(ProviderError, UnavailableError):
    """
    当Provider不可用时引发此异常
    """

    pass


class ProviderRequestTimeoutError(ProviderUnavailableError, RequestTimeoutError):
    """
    当Provider请求超时时引发此异常
    """

    pass


class ProviderRateLimitError(ProviderUnavailableError, RateLimitError):
    """
    当Provider出现请求速率限制时引发此异常
    """

    pass


class ProviderAuthorizationError(ProviderUnavailableError, AuthorizationError):
    """
    当Provider授权错误时引发此异常
    """

    pass
