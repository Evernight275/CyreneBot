from __future__ import annotations

from cyreneAI.core.schema.skill import (
    SkillDefinition,
    SkillInstruction,
    SkillInstructionBundle,
    SkillSelection,
    SkillSelectionRequest,
)


def test_skill_definition_defaults() -> None:
    definition = SkillDefinition(
        name="memory",
        description="Use memory.",
        instructions="Prefer relevant memory when answering.",
    )

    assert definition.triggers == []
    assert definition.priority == 0
    assert definition.enabled is True
    assert definition.allowed_tools == []
    assert definition.required_context == []
    assert definition.metadata == {}


def test_skill_selection_request_defaults() -> None:
    request = SkillSelectionRequest()

    assert request.text == ""
    assert request.required_skill_names == []
    assert request.max_skills is None
    assert request.metadata == {}


def test_skill_selection_and_instruction_bundle_schema() -> None:
    definition = SkillDefinition(
        name="memory",
        description="Use memory.",
        instructions="Prefer relevant memory when answering.",
        priority=10,
    )
    selection = SkillSelection(
        definition=definition,
        score=11.0,
        reason="matched triggers: memory",
    )
    instruction = SkillInstruction(
        name=definition.name,
        content=definition.instructions,
        priority=definition.priority,
    )
    bundle = SkillInstructionBundle(
        instructions=[instruction],
        allowed_tools=["search_memory"],
        required_context=["conversation"],
    )

    assert selection.definition is definition
    assert bundle.instructions == [instruction]
    assert bundle.allowed_tools == ["search_memory"]
    assert bundle.required_context == ["conversation"]
