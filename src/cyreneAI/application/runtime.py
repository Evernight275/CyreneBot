from __future__ import annotations

from dataclasses import dataclass

from cyreneAI.core.context.context_protocol import ContextBuilderProtocol
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.errors.base import StateError
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.skill.manager import SkillManager
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.tool_protocol import ToolRegistryProtocol
from cyreneAI.core.vector.manager import VectorManager


@dataclass(slots=True)
class CyreneAIRuntime:
    """
    CyreneAI 应用运行时
    """

    provider_manager: ProviderManager
    context_builder: ContextBuilderProtocol
    context_manager: ContextManager | None = None
    vector_manager: VectorManager | None = None
    skill_manager: SkillManager | None = None
    tool_registry: ToolRegistryProtocol | None = None
    tool_manager: ToolManager | None = None

    async def close(self) -> None:
        """
        关闭运行时持有的外部资源。
        """
        errors: list[Exception] = []

        try:
            await self.provider_manager.close_all()
        except Exception as exc:
            errors.append(exc)

        if self.context_manager is not None:
            try:
                await self.context_manager.close()
            except Exception as exc:
                errors.append(exc)

        if self.vector_manager is not None:
            try:
                await self.vector_manager.close()
            except Exception as exc:
                errors.append(exc)

        if errors:
            raise StateError(
                f"Failed to close {len(errors)} runtime resource(s)",
                cause=errors[0],
            )
