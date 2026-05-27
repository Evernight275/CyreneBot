from __future__ import annotations

from cyreneAI.core.schema.skill import SkillDefinition, SkillSelectionRequest
from cyreneAI.core.skill.policy import (
    build_skill_instruction_bundle,
    select_skill_definitions,
)


def test_select_skill_definitions_matches_triggers_by_priority() -> None:
    memory = SkillDefinition(
        name="memory",
        description="Use memory.",
        instructions="Prefer relevant memory when answering.",
        triggers=["memory"],
        priority=5,
    )
    concise = SkillDefinition(
        name="concise",
        description="Answer concisely.",
        instructions="Keep the answer concise.",
        triggers=["answer"],
        priority=1,
    )
    disabled = SkillDefinition(
        name="disabled",
        description="Disabled skill.",
        instructions="Do not use.",
        triggers=["memory"],
        enabled=False,
        priority=100,
    )

    selections = select_skill_definitions(
        SkillSelectionRequest(text="Answer with memory."),
        [concise, disabled, memory],
    )

    assert [selection.definition.name for selection in selections] == [
        "memory",
        "concise",
    ]
    assert selections[0].reason == "matched triggers: memory"


def test_select_skill_definitions_keeps_required_skills_first() -> None:
    memory = SkillDefinition(
        name="memory",
        description="Use memory.",
        instructions="Prefer relevant memory when answering.",
    )
    concise = SkillDefinition(
        name="concise",
        description="Answer concisely.",
        instructions="Keep the answer concise.",
        triggers=["answer"],
        priority=1,
    )

    selections = select_skill_definitions(
        SkillSelectionRequest(
            text="Answer shortly.",
            required_skill_names=["memory"],
            max_skills=1,
        ),
        [concise, memory],
    )

    assert [selection.definition.name for selection in selections] == ["memory"]
    assert selections[0].reason == "required"


def test_build_skill_instruction_bundle_merges_selected_skill_requirements() -> None:
    memory = SkillDefinition(
        name="memory",
        description="Use memory.",
        instructions="Prefer relevant memory.",
        allowed_tools=["search_memory", "read_context"],
        required_context=["conversation"],
    )
    planner = SkillDefinition(
        name="planner",
        description="Plan work.",
        instructions="Break work into steps.",
        allowed_tools=["read_context"],
        required_context=["conversation", "workspace"],
    )

    selections = select_skill_definitions(
        SkillSelectionRequest(required_skill_names=["memory", "planner"]),
        [memory, planner],
    )
    bundle = build_skill_instruction_bundle(selections)

    assert [instruction.name for instruction in bundle.instructions] == [
        "planner",
        "memory",
    ]
    assert bundle.allowed_tools == [
        "read_context",
        "search_memory",
    ]
    assert bundle.required_context == [
        "conversation",
        "workspace",
    ]
    assert bundle.metadata == {"skills": ["planner", "memory"]}
