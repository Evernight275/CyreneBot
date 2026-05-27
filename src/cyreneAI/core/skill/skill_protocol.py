from __future__ import annotations

from typing import Protocol

from cyreneAI.core.schema.skill import (
    SkillDefinition,
    SkillSelection,
    SkillSelectionRequest,
)


class SkillRegistryProtocol(Protocol):
    """
    技能注册器协议
    """

    def register(self, definition: SkillDefinition) -> None:
        """
        注册技能
        """
        ...

    def unregister(self, name: str) -> None:
        """
        注销技能
        """
        ...

    def get_definition(self, name: str) -> SkillDefinition:
        """
        获取技能定义
        """
        ...

    def exists(self, name: str) -> bool:
        """
        判断技能是否存在
        """
        ...

    def list_definitions(self) -> list[SkillDefinition]:
        """
        列出技能定义
        """
        ...


class SkillSelectorProtocol(Protocol):
    """
    技能选择器协议
    """

    def select(
        self,
        request: SkillSelectionRequest,
        definitions: list[SkillDefinition],
    ) -> list[SkillSelection]:
        """
        选择技能
        """
        ...


class SkillLoaderProtocol(Protocol):
    """
    技能加载器协议
    """

    def load(self) -> list[SkillDefinition]:
        """
        加载技能定义
        """
        ...
