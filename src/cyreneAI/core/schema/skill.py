from __future__ import annotations

from typing import Any

from pydantic import Field

from cyreneAI.core.schema.base import CyreneAISchema


class SkillDefinition(CyreneAISchema):
    """
    技能定义schema
    """

    name: str
    description: str
    instructions: str
    triggers: list[str] = Field(default_factory=list)
    priority: int = 0
    enabled: bool = True
    allowed_tools: list[str] = Field(default_factory=list)
    required_context: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillSelectionRequest(CyreneAISchema):
    """
    技能选择请求schema
    """

    text: str = ""
    required_skill_names: list[str] = Field(default_factory=list)
    max_skills: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillSelection(CyreneAISchema):
    """
    技能选择结果schema
    """

    definition: SkillDefinition
    score: float = 0.0
    reason: str | None = None


class SkillInstruction(CyreneAISchema):
    """
    技能提示词片段schema
    """

    name: str
    content: str
    priority: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillInstructionBundle(CyreneAISchema):
    """
    技能提示词集合schema
    """

    instructions: list[SkillInstruction] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    required_context: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
