from __future__ import annotations

from cyreneAI.core.schema.skill import (
    SkillDefinition,
    SkillSelection,
    SkillSelectionRequest,
)
from cyreneAI.core.skill.policy import select_skill_definitions


class RuleBasedSkillSelector:
    """
    基于规则的技能选择器
    """

    def select(
        self,
        request: SkillSelectionRequest,
        definitions: list[SkillDefinition],
    ) -> list[SkillSelection]:
        """
        选择技能
        """
        return select_skill_definitions(request, definitions)
