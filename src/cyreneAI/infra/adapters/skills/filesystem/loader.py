from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from cyreneAI.core.errors.skill import SkillConfigurationError, SkillInputError
from cyreneAI.core.schema.skill import SkillDefinition


class FileSystemSkillLoader:
    """
    文件系统技能加载器
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> list[SkillDefinition]:
        """
        加载技能定义
        """
        if not self._path.exists():
            raise SkillConfigurationError(
                f"Skill path {self._path} does not exist"
            )

        if self._path.is_file():
            return _load_skill_file(self._path)

        if self._path.is_dir():
            definitions: list[SkillDefinition] = []
            for path in sorted(self._path.glob("*.json")):
                definitions.extend(_load_skill_file(path))
            return definitions

        raise SkillConfigurationError(
            f"Skill path {self._path} must be a file or directory"
        )


def _load_skill_file(path: Path) -> list[SkillDefinition]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise SkillInputError(
            f"Skill file {path} must contain valid JSON",
            cause=exc,
        ) from exc

    try:
        return _map_skill_payload(payload)
    except PydanticValidationError as exc:
        raise SkillInputError(
            f"Skill file {path} contains invalid skill definition",
            cause=exc,
        ) from exc


def _map_skill_payload(payload: Any) -> list[SkillDefinition]:
    if isinstance(payload, list):
        return [SkillDefinition.model_validate(item) for item in payload]
    return [SkillDefinition.model_validate(payload)]
