from __future__ import annotations

from cyreneAI.core.errors.base import (
    ConfigurationError,
    CyreneAIError,
    NotFoundError,
    StateError,
    ValidationError,
)
from cyreneAI.core.errors.skill import (
    SkillConfigurationError,
    SkillError,
    SkillInputError,
    SkillNotFoundError,
    SkillSelectionError,
    SkillStateError,
)


def test_skill_errors_inherit_from_base_error() -> None:
    assert isinstance(SkillError("skill failed"), CyreneAIError)
    assert isinstance(SkillInputError("input failed"), SkillError)
    assert isinstance(SkillNotFoundError("not found"), SkillError)
    assert isinstance(SkillConfigurationError("bad config"), SkillError)
    assert isinstance(SkillSelectionError("selection failed"), SkillError)
    assert isinstance(SkillStateError("bad state"), SkillError)


def test_skill_errors_use_specific_base_categories() -> None:
    assert isinstance(SkillInputError("input failed"), ValidationError)
    assert isinstance(SkillNotFoundError("not found"), NotFoundError)
    assert isinstance(SkillConfigurationError("bad config"), ConfigurationError)
    assert isinstance(SkillSelectionError("selection failed"), StateError)
    assert isinstance(SkillStateError("bad state"), StateError)


def test_skill_error_keeps_cause() -> None:
    cause = RuntimeError("boom")
    error = SkillSelectionError("selection failed", cause=cause)

    assert error.cause is cause
