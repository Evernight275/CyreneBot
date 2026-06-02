from __future__ import annotations

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.application.tools import (
    register_core_builtin_tools,
    register_memory_tools,
    register_todo_tools,
)
from cyreneAI.application.plugins.builtin_bot_commands import (
    register_builtin_bot_command_plugins,
)
from cyreneAI.application.plugins.host import PluginHost
from cyreneAI.application.plugins.outbox import ApplicationPluginOutbox
from cyreneAI.application.plugins.tasks import ApplicationPluginTaskScheduler
from cyreneAI.core.bot.bot_protocol import BotChannelRegistryProtocol
from cyreneAI.core.bot.polling_protocol import BotPollingStateStoreProtocol
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.context.context_protocol import ContextBuilderProtocol
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.plugin.manager import PluginManager
from cyreneAI.core.plugin.plugin_protocol import (
    PluginAssetsProtocol,
    PluginLoaderProtocol,
    PluginRegistryProtocol,
    PluginStorageProtocol,
    PluginTaskSchedulerProtocol,
    PluginTaskStoreProtocol,
)
from cyreneAI.core.plugin.registry import PluginRegistry
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.application import BotAdminConfig
from cyreneAI.core.schema.provider import ProviderConfig
from cyreneAI.core.skill.manager import SkillManager
from cyreneAI.core.skill.skill_protocol import SkillRegistryProtocol
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.registry import ToolRegistry
from cyreneAI.core.tool.tool_protocol import (
    ToolRegistryProtocol,
    ToolSandboxRunnerProtocol,
)
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
    skill_registry: SkillRegistryProtocol | None = None,
    plugin_registry: PluginRegistryProtocol | None = None,
    plugin_manager: PluginManager | None = None,
    plugin_loaders: list[PluginLoaderProtocol] | None = None,
    plugin_storage: PluginStorageProtocol | None = None,
    plugin_assets: PluginAssetsProtocol | None = None,
    plugin_task_scheduler: PluginTaskSchedulerProtocol | None = None,
    plugin_task_store: PluginTaskStoreProtocol | None = None,
    disabled_plugin_ids: list[str] | None = None,
    plugin_fail_fast: bool = True,
    register_builtin_plugins: bool = True,
    register_builtin_tools: bool = True,
    tool_registry: ToolRegistryProtocol | None = None,
    tool_sandbox_runner: ToolSandboxRunnerProtocol | None = None,
    vector_store: VectorStoreProtocol | None = None,
    bot_channel_registry: BotChannelRegistryProtocol | None = None,
    bot_session_manager: BotSessionManager | None = None,
    bot_polling_state_store: BotPollingStateStoreProtocol | None = None,
    bot_admin_config: BotAdminConfig | None = None,
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
    runtime_plugin_registry = plugin_registry or PluginRegistry()
    runtime_plugin_manager = plugin_manager or PluginManager(runtime_plugin_registry)
    if plugin_task_scheduler is not None and plugin_task_store is not None:
        raise ValueError(
            "plugin_task_scheduler and plugin_task_store cannot both be set"
        )
    runtime_plugin_task_scheduler = plugin_task_scheduler
    if runtime_plugin_task_scheduler is None:
        runtime_plugin_task_scheduler = ApplicationPluginTaskScheduler(
            store=plugin_task_store,
        )
    await runtime_plugin_task_scheduler.start()

    runtime = CyreneAIRuntime(
        provider_manager=runtime_provider_manager,
        context_builder=context_builder or ContextWindowBuilder(),
        context_manager=context_manager,
        vector_manager=(
            VectorManager(vector_store)
            if vector_store is not None
            else None
        ),
        skill_manager=skill_manager,
        plugin_manager=runtime_plugin_manager,
        plugin_storage=plugin_storage,
        plugin_assets=plugin_assets,
        plugin_task_scheduler=runtime_plugin_task_scheduler,
        tool_registry=runtime_tool_registry,
        tool_manager=ToolManager(
            runtime_tool_registry,
            sandbox_runner=tool_sandbox_runner,
        ),
        tool_sandbox_runner=tool_sandbox_runner,
        bot_channel_registry=bot_channel_registry,
        bot_session_manager=bot_session_manager,
        bot_polling_state_store=bot_polling_state_store,
        bot_admin_config=bot_admin_config,
    )
    runtime.plugin_outbox = ApplicationPluginOutbox(runtime)
    if register_builtin_tools:
        register_core_builtin_tools(runtime_tool_registry)
        register_todo_tools(runtime_tool_registry)
        register_memory_tools(runtime)

    runtime_plugin_host = PluginHost(
        runtime=runtime,
        registry=runtime_plugin_registry,
        skill_registry=skill_registry,
        disabled_plugin_ids=set(disabled_plugin_ids or []),
        fail_fast=plugin_fail_fast,
    )
    runtime.plugin_host = runtime_plugin_host

    if register_builtin_plugins:
        register_builtin_bot_command_plugins(runtime_plugin_registry, runtime)
    for plugin_loader in plugin_loaders or []:
        runtime_plugin_host.load(plugin_loader)

    return runtime


__all__ = ["build_cyrene_ai_runtime"]
