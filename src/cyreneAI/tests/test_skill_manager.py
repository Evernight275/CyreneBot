from __future__ import annotations

from pathlib import Path

from cyreneAI.core.schema.skill import SkillDefinition, SkillSelectionRequest
from cyreneAI.core.skill.manager import SkillManager
from cyreneAI.core.skill.registry import SkillRegistry


def test_skill_manager_selects_skills_and_builds_instruction_bundle() -> None:
    registry = SkillRegistry()
    registry.register(
        SkillDefinition(
            name="memory",
            description="Use memory.",
            instructions="Prefer relevant memory.",
            triggers=["memory"],
            allowed_tools=["search_memory"],
            required_context=["conversation"],
        )
    )
    manager = SkillManager(registry)

    selections = manager.select(SkillSelectionRequest(text="Use memory."))
    bundle = manager.build_instruction_bundle(
        SkillSelectionRequest(text="Use memory.")
    )

    assert [selection.definition.name for selection in selections] == ["memory"]
    assert [instruction.name for instruction in bundle.instructions] == ["memory"]
    assert bundle.allowed_tools == ["search_memory"]
    assert bundle.required_context == ["conversation"]


def test_core_skill_does_not_import_infra_or_external_sdks() -> None:
    skill_dir = Path(__file__).parents[1] / "core" / "skill"
    forbidden_patterns = [
        "cyreneAI.infra",
        "openai",
        "anthropic",
        "google.genai",
        "httpx",
        "dotenv",
        "os.getenv",
    ]

    for path in skill_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            assert pattern not in text
