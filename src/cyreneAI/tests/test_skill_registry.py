from __future__ import annotations

import pytest

from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.skill import SkillNotFoundError
from cyreneAI.core.schema.skill import SkillDefinition
from cyreneAI.core.skill.registry import SkillRegistry


def _definition(name: str = "memory") -> SkillDefinition:
    return SkillDefinition(
        name=name,
        description="Use memory.",
        instructions="Prefer relevant memory when answering.",
    )


def test_skill_registry_registers_and_lists_skills() -> None:
    registry = SkillRegistry()
    definition = _definition()

    registry.register(definition)

    assert registry.exists("memory")
    assert registry.get_definition("memory") is definition
    assert registry.list_definitions() == [definition]


def test_skill_registry_rejects_duplicate_skills() -> None:
    registry = SkillRegistry()

    registry.register(_definition())

    with pytest.raises(ConflictError):
        registry.register(_definition())


def test_skill_registry_raises_when_skill_is_missing() -> None:
    registry = SkillRegistry()

    with pytest.raises(SkillNotFoundError):
        registry.get_definition("missing")

    with pytest.raises(SkillNotFoundError):
        registry.unregister("missing")


def test_skill_registry_unregisters_skills() -> None:
    registry = SkillRegistry()

    registry.register(_definition())
    registry.unregister("memory")

    assert not registry.exists("memory")
