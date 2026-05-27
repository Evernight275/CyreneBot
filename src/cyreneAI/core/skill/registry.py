from __future__ import annotations

from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.skill import SkillNotFoundError
from cyreneAI.core.schema.skill import SkillDefinition


class SkillRegistry:
    """
    技能注册器
    """

    def __init__(self) -> None:
        self._definitions: dict[str, SkillDefinition] = {}

    def register(self, definition: SkillDefinition) -> None:
        """
        注册技能
        """
        if definition.name in self._definitions:
            raise ConflictError(f"该技能 {definition.name} 已注册")
        self._definitions[definition.name] = definition

    def unregister(self, name: str) -> None:
        """
        注销技能
        """
        if name not in self._definitions:
            raise SkillNotFoundError(f"该技能 {name} 不存在")
        self._definitions.pop(name, None)

    def get_definition(self, name: str) -> SkillDefinition:
        """
        获取技能定义
        """
        definition = self._definitions.get(name)
        if definition is None:
            raise SkillNotFoundError(f"该技能 {name} 不存在")
        return definition

    def exists(self, name: str) -> bool:
        """
        判断技能是否存在
        """
        return name in self._definitions

    def list_definitions(self) -> list[SkillDefinition]:
        """
        列出技能定义
        """
        return list(self._definitions.values())
