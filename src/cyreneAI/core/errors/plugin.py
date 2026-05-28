from __future__ import annotations

from cyreneAI.core.errors.base import (
    AuthorizationError,
    ConfigurationError,
    CyreneAIError,
    NotFoundError,
    StateError,
    ValidationError,
)


class PluginError(CyreneAIError):
    """
    插件通用错误。
    """

    pass


class PluginInputError(PluginError, ValidationError):
    """
    插件输入错误。
    """

    pass


class PluginNotFoundError(PluginError, NotFoundError):
    """
    插件不存在。
    """

    pass


class PluginConfigurationError(PluginError, ConfigurationError):
    """
    插件配置错误。
    """

    pass


class PluginAuthorizationError(PluginError, AuthorizationError):
    """
    插件权限错误。
    """

    pass


class PluginExecutionError(PluginError):
    """
    插件执行错误。
    """

    pass


class PluginStateError(PluginError, StateError):
    """
    插件状态错误。
    """

    pass
