from __future__ import annotations

from cyreneAI.core.errors.base import (
    ConfigurationError,
    CyreneAIError,
    NotFoundError,
    RequestError,
    StateError,
    UnsupportedError,
    ValidationError,
)


class BotError(CyreneAIError):
    """
    这里定义了与 bot 内核相关的通用异常。
    """

    pass


class BotInputError(BotError, ValidationError):
    """
    当 bot 输入事件不合法时引发此异常。
    """

    pass


class BotUnsupportedEventError(BotError, UnsupportedError):
    """
    当 bot 事件类型不支持时引发此异常。
    """

    pass


class BotConfigurationError(BotError, ConfigurationError):
    """
    当 bot 配置错误时引发此异常。
    """

    pass


class BotChannelNotFoundError(BotError, NotFoundError):
    """
    当请求的 bot channel 不存在时引发此异常。
    """

    pass


class BotSessionNotFoundError(BotError, NotFoundError):
    """
    当请求的 bot session 不存在时引发此异常。
    """

    pass


class BotActionError(BotError, RequestError):
    """
    当 bot 动作无法生成或发送时引发此异常。
    """

    pass


class BotStateError(BotError, StateError):
    """
    当 bot 运行状态不合法时引发此异常。
    """

    pass
