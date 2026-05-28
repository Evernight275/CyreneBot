from __future__ import annotations

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.bot.bot_protocol import BotChannelRegistryProtocol
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.context.context_protocol import ContextBuilderProtocol
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.provider import ProviderConfig
from cyreneAI.core.skill.manager import SkillManager
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.registry import ToolRegistry
from cyreneAI.core.tool.tool_protocol import ToolRegistryProtocol
from cyreneAI.core.vector.manager import VectorManager
from cyreneAI.core.vector.vector_protocol import VectorStoreProtocol


async def build_cyrene_ai_runtime(
    *,
    provider_manager: ProviderManager | None = None,
    provider_factory: ProviderFactory | None = None,
    provider_configs: list[ProviderConfig] | None = None,
    context_builder: ContextBuilderProtocol | None = None,
    context_manager: ContextManager | None = None,
    skill_manager: SkillManager | None = None,
    tool_registry: ToolRegistryProtocol | None = None,
    vector_store: VectorStoreProtocol | None = None,
    bot_channel_registry: BotChannelRegistryProtocol | None = None,
    bot_session_manager: BotSessionManager | None = None,
) -> CyreneAIRuntime:
    """
    构建只依赖 core protocol/manager 的应用运行时。
    """
    runtime_provider_manager = provider_manager
    if runtime_provider_manager is None:
        runtime_provider_manager = ProviderManager(provider_factory or ProviderFactory())

    for config in provider_configs or []:
        if config.enabled:
            await runtime_provider_manager.add(config)

    runtime_tool_registry = tool_registry or ToolRegistry()
    return CyreneAIRuntime(
        provider_manager=runtime_provider_manager,
        context_builder=context_builder or ContextWindowBuilder(),
        context_manager=context_manager,
        vector_manager=(
            VectorManager(vector_store)
            if vector_store is not None
            else None
        ),
        skill_manager=skill_manager,
        tool_registry=runtime_tool_registry,
        tool_manager=ToolManager(runtime_tool_registry),
        bot_channel_registry=bot_channel_registry,
        bot_session_manager=bot_session_manager,
    )


__all__ = ["build_cyrene_ai_runtime"]
