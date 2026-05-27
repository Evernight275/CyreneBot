from __future__ import annotations

from cyreneAI.core.errors.base import (
    ConfigurationError,
    CyreneAIError,
    NotFoundError,
    StateError,
    ValidationError,
)


class SkillError(CyreneAIError):
    """
    这里定义了与技能相关的通用异常
    """

    pass


class SkillInputError(SkillError, ValidationError):
    """
    当技能输入不合法时引发此异常
    """

    pass


class SkillNotFoundError(SkillError, NotFoundError):
    """
    当请求的技能不存在时引发此异常
    """

    pass


class SkillConfigurationError(SkillError, ConfigurationError):
    """
    当技能配置错误时引发此异常
    """

    pass


class SkillSelectionError(SkillError, StateError):
    """
    当技能选择失败时引发此异常
    """

    pass


class SkillStateError(SkillError, StateError):
    """
    当技能状态不合法时引发此异常
    """

    pass
