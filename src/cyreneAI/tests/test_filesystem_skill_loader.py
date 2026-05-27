from __future__ import annotations

import json

import pytest

from cyreneAI.core.errors.skill import SkillConfigurationError, SkillInputError
from cyreneAI.core.schema.skill import SkillSelectionRequest
from cyreneAI.core.skill.manager import SkillManager
from cyreneAI.core.skill.registry import SkillRegistry
from cyreneAI.infra.adapters.skills.filesystem.loader import FileSystemSkillLoader


def test_filesystem_skill_loader_loads_single_skill_file(tmp_path) -> None:
    path = tmp_path / "memory.json"
    path.write_text(
        json.dumps(
            {
                "name": "memory",
                "description": "Use memory.",
                "instructions": "Prefer relevant memory.",
                "triggers": ["memory"],
                "allowed_tools": ["search_memory"],
                "required_context": ["conversation"],
            }
        ),
        encoding="utf-8",
    )

    definitions = FileSystemSkillLoader(path).load()

    assert len(definitions) == 1
    assert definitions[0].name == "memory"
    assert definitions[0].instructions == "Prefer relevant memory."
    assert definitions[0].allowed_tools == ["search_memory"]
    assert definitions[0].required_context == ["conversation"]


def test_filesystem_skill_loader_loads_directory_in_file_order(tmp_path) -> None:
    (tmp_path / "02_planner.json").write_text(
        json.dumps(
            {
                "name": "planner",
                "description": "Plan work.",
                "instructions": "Break work into steps.",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "01_memory.json").write_text(
        json.dumps(
            {
                "name": "memory",
                "description": "Use memory.",
                "instructions": "Prefer relevant memory.",
            }
        ),
        encoding="utf-8",
    )

    definitions = FileSystemSkillLoader(tmp_path).load()

    assert [definition.name for definition in definitions] == [
        "memory",
        "planner",
    ]


def test_filesystem_skill_loader_rejects_missing_path(tmp_path) -> None:
    with pytest.raises(SkillConfigurationError):
        FileSystemSkillLoader(tmp_path / "missing.json").load()


def test_filesystem_skill_loader_rejects_invalid_json(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(SkillInputError):
        FileSystemSkillLoader(path).load()


def test_filesystem_skill_loader_integrates_with_skill_manager(tmp_path) -> None:
    path = tmp_path / "skills.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "memory",
                    "description": "Use memory.",
                    "instructions": "Prefer relevant memory.",
                    "triggers": ["memory"],
                }
            ]
        ),
        encoding="utf-8",
    )
    registry = SkillRegistry()
    for definition in FileSystemSkillLoader(path).load():
        registry.register(definition)

    bundle = SkillManager(registry).build_instruction_bundle(
        SkillSelectionRequest(text="Use memory.")
    )

    assert [instruction.name for instruction in bundle.instructions] == ["memory"]
    assert bundle.instructions[0].content == "Prefer relevant memory."
