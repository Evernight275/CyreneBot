from __future__ import annotations

from pathlib import Path

from cyreneAI.application.bootstrap import (
    build_cyrene_ai_runtime as build_application_runtime,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.bot.bot_protocol import BotChannelRegistryProtocol
from cyreneAI.core.bot.polling_protocol import BotPollingStateStoreProtocol
from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.bot.session_protocol import BotSessionStoreProtocol
from cyreneAI.core.context.context_protocol import ContextBuilderProtocol
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.plugin.plugin_protocol import (
    PluginAssetsProtocol,
    PluginLoaderProtocol,
    PluginStorageProtocol,
    PluginTaskSchedulerProtocol,
    PluginTaskStoreProtocol,
)
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.provider import ProviderConfig
from cyreneAI.core.skill.manager import SkillManager
from cyreneAI.core.skill.registry import SkillRegistry
from cyreneAI.core.tool.tool_protocol import ToolRegistryProtocol
from cyreneAI.core.vector.vector_protocol import VectorStoreProtocol
from cyreneAI.infra.adapters.skills.filesystem.loader import FileSystemSkillLoader
from cyreneAI.infra.adapters.bot_polling_states.sqlite.builder import (
    create_sqlite_bot_polling_state_store,
)
from cyreneAI.infra.adapters.plugins.filesystem import FileSystemPluginStorage
from cyreneAI.infra.adapters.plugins.sqlite import create_sqlite_plugin_task_store
from cyreneAI.infra.adapters.bot_sessions.memory import InMemoryBotSessionStore
from cyreneAI.infra.adapters.vector_stores.sqlite.builder import (
    create_sqlite_vector_store,
)
from cyreneAI.infra.bootstrap.registrations.bot_channels import (
    register_default_bot_channels,
)
from cyreneAI.infra.bootstrap.registrations.providers import register_default_providers
from cyreneAI.infra.bootstrap.registrations.telegram_bot_channel import (
    register_telegram_bot_channel,
)
from cyreneAI.infra.database.sqlite.builder import create_sqlite_context_store


async def build_cyrene_ai_runtime(
    *,
    provider_configs: list[ProviderConfig] | None = None,
    context_database_path: str | Path | None = None,
    skill_path: str | Path | None = None,
    context_builder: ContextBuilderProtocol | None = None,
    tool_registry: ToolRegistryProtocol | None = None,
    vector_store: VectorStoreProtocol | None = None,
    vector_database_path: str | Path | None = None,
    bot_channel_registry: BotChannelRegistryProtocol | None = None,
    enable_memory_bot_channel: bool = False,
    telegram_bot_token: str | None = None,
    bot_session_store: BotSessionStoreProtocol | None = None,
    bot_session_manager: BotSessionManager | None = None,
    bot_polling_state_store: BotPollingStateStoreProtocol | None = None,
    bot_polling_state_database_path: str | Path | None = None,
    plugin_loaders: list[PluginLoaderProtocol] | None = None,
    plugin_storage: PluginStorageProtocol | None = None,
    plugin_storage_path: str | Path | None = None,
    plugin_assets: PluginAssetsProtocol | None = None,
    plugin_task_scheduler: PluginTaskSchedulerProtocol | None = None,
    plugin_task_store: PluginTaskStoreProtocol | None = None,
    plugin_task_database_path: str | Path | None = None,
    disabled_plugin_ids: list[str] | None = None,
    plugin_fail_fast: bool = True,
    register_builtin_plugins: bool = True,
) -> CyreneAIRuntime:
    """
    构建带默认 infra 适配的 CyreneAI 运行时。
    """
    provider_registry = ProviderRegistry()
    provider_factory = ProviderFactory()
    register_default_providers(provider_registry, provider_factory)
    provider_manager = ProviderManager(provider_factory)

    for config in provider_configs or []:
        if config.enabled:
            await provider_manager.add(config)

    context_manager = None
    if context_database_path is not None:
        context_manager = ContextManager(
            await create_sqlite_context_store(context_database_path)
        )

    skill_manager = None
    skill_registry = None
    if skill_path is not None:
        skill_registry = SkillRegistry()
        for definition in FileSystemSkillLoader(skill_path).load():
            skill_registry.register(definition)
        skill_manager = SkillManager(skill_registry)

    runtime_vector_store = vector_store
    if runtime_vector_store is not None and vector_database_path is not None:
        raise ValueError("vector_store and vector_database_path cannot both be set")
    if runtime_vector_store is None and vector_database_path is not None:
        runtime_vector_store = await create_sqlite_vector_store(vector_database_path)

    runtime_bot_session_manager = bot_session_manager
    if runtime_bot_session_manager is not None and bot_session_store is not None:
        raise ValueError("bot_session_store and bot_session_manager cannot both be set")
    if runtime_bot_session_manager is None and bot_session_store is not None:
        runtime_bot_session_manager = BotSessionManager(bot_session_store)

    runtime_bot_polling_state_store = bot_polling_state_store
    if (
        runtime_bot_polling_state_store is not None
        and bot_polling_state_database_path is not None
    ):
        raise ValueError(
            "bot_polling_state_store and bot_polling_state_database_path cannot both be set"
        )
    if (
        runtime_bot_polling_state_store is None
        and bot_polling_state_database_path is not None
    ):
        runtime_bot_polling_state_store = await create_sqlite_bot_polling_state_store(
            bot_polling_state_database_path
        )

    runtime_plugin_storage = plugin_storage
    if runtime_plugin_storage is not None and plugin_storage_path is not None:
        raise ValueError("plugin_storage and plugin_storage_path cannot both be set")
    if runtime_plugin_storage is None and plugin_storage_path is not None:
        runtime_plugin_storage = FileSystemPluginStorage(plugin_storage_path)

    if plugin_task_scheduler is not None and (
        plugin_task_store is not None or plugin_task_database_path is not None
    ):
        raise ValueError(
            "plugin_task_scheduler cannot be combined with plugin task store options"
        )

    runtime_plugin_task_store = plugin_task_store
    if (
        runtime_plugin_task_store is not None
        and plugin_task_database_path is not None
    ):
        raise ValueError(
            "plugin_task_store and plugin_task_database_path cannot both be set"
        )
    if runtime_plugin_task_store is None and plugin_task_database_path is not None:
        runtime_plugin_task_store = await create_sqlite_plugin_task_store(
            plugin_task_database_path
        )

    runtime_bot_channel_registry = bot_channel_registry
    if enable_memory_bot_channel or telegram_bot_token:
        if runtime_bot_channel_registry is None:
            runtime_bot_channel_registry = BotChannelRegistry()
    if enable_memory_bot_channel:
        register_default_bot_channels(runtime_bot_channel_registry)
    if telegram_bot_token:
        register_telegram_bot_channel(
            runtime_bot_channel_registry,
            token=telegram_bot_token,
        )

    if (
        runtime_bot_session_manager is None
        and runtime_bot_channel_registry is not None
    ):
        runtime_bot_session_manager = BotSessionManager(InMemoryBotSessionStore())

    return await build_application_runtime(
        provider_manager=provider_manager,
        context_builder=context_builder,
        context_manager=context_manager,
        skill_manager=skill_manager,
        skill_registry=skill_registry if skill_path is not None else None,
        plugin_loaders=plugin_loaders,
        plugin_storage=runtime_plugin_storage,
        plugin_assets=plugin_assets,
        plugin_task_scheduler=plugin_task_scheduler,
        plugin_task_store=runtime_plugin_task_store,
        disabled_plugin_ids=disabled_plugin_ids,
        plugin_fail_fast=plugin_fail_fast,
        register_builtin_plugins=register_builtin_plugins,
        tool_registry=tool_registry,
        vector_store=runtime_vector_store,
        bot_channel_registry=runtime_bot_channel_registry,
        bot_session_manager=runtime_bot_session_manager,
        bot_polling_state_store=runtime_bot_polling_state_store,
    )


__all__ = ["build_cyrene_ai_runtime"]
