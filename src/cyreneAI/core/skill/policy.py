from __future__ import annotations

from cyreneAI.core.schema.skill import (
    SkillDefinition,
    SkillInstruction,
    SkillInstructionBundle,
    SkillSelection,
    SkillSelectionRequest,
)


def select_skill_definitions(
    request: SkillSelectionRequest,
    definitions: list[SkillDefinition],
) -> list[SkillSelection]:
    """
    按请求选择技能定义
    """
    selections: list[SkillSelection] = []
    required_names = set(request.required_skill_names)
    request_text = request.text.casefold()

    for definition in definitions:
        if not definition.enabled:
            continue

        if definition.name in required_names:
            selections.append(
                SkillSelection(
                    definition=definition,
                    score=float(definition.priority + 1000),
                    reason="required",
                )
            )
            continue

        matched_triggers = [
            trigger
            for trigger in definition.triggers
            if trigger and trigger.casefold() in request_text
        ]
        if not matched_triggers:
            continue

        selections.append(
            SkillSelection(
                definition=definition,
                score=float(definition.priority + len(matched_triggers)),
                reason=f"matched triggers: {', '.join(matched_triggers)}",
            )
        )

    selections.sort(
        key=lambda selection: (
            selection.score,
            selection.definition.priority,
            selection.definition.name,
        ),
        reverse=True,
    )

    if request.max_skills is not None:
        return selections[: request.max_skills]
    return selections


def build_skill_instruction_bundle(
    selections: list[SkillSelection],
) -> SkillInstructionBundle:
    """
    将已选择技能构造成提示词集合
    """
    return SkillInstructionBundle(
        instructions=[
            SkillInstruction(
                name=selection.definition.name,
                content=selection.definition.instructions,
                priority=selection.definition.priority,
                metadata={
                    "score": selection.score,
                    "reason": selection.reason,
                },
            )
            for selection in selections
        ],
        allowed_tools=_deduplicate(
            tool
            for selection in selections
            for tool in selection.definition.allowed_tools
        ),
        required_context=_deduplicate(
            context
            for selection in selections
            for context in selection.definition.required_context
        ),
        metadata={
            "skills": [selection.definition.name for selection in selections],
        },
    )


def _deduplicate(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
