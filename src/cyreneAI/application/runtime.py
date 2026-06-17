from __future__ import annotations

from dataclasses import dataclass

from cyreneAI.core.bot.bot_protocol import BotChannelRegistryProtocol
from cyreneAI.core.bot.polling_protocol import BotPollingStateStoreProtocol
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.context.context_protocol import ContextBuilderProtocol
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.errors.base import StateError
from cyreneAI.core.plugin.manager import PluginManager
from cyreneAI.core.plugin.plugin_protocol import (
    PluginAssetsProtocol,
    PluginOutboxProtocol,
    PluginPythonEnvironmentManagerProtocol,
    PluginStorageProtocol,
    PluginTaskSchedulerProtocol,
)
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.provider.provider_protocol import ProviderConfigStoreProtocol
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.runtime.runtime_protocol import (
    CyreneAIRuntimeProtocol,
    PluginHostProtocol,
)
from cyreneAI.core.schema.application import BotAdminConfig
from cyreneAI.core.skill.manager import SkillManager
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.tool_protocol import (
    ToolRegistryProtocol,
    ToolSandboxRunnerProtocol,
)
from cyreneAI.core.vector.manager import VectorManager


@dataclass(slots=True)
class CyreneAIRuntime(CyreneAIRuntimeProtocol):
    """
    CyreneAI 应用运行时
    """

    provider_manager: ProviderManager
    context_builder: ContextBuilderProtocol
    provider_registry: ProviderRegistry | None = None
    provider_config_store: ProviderConfigStoreProtocol | None = None
    context_manager: ContextManager | None = None
    vector_manager: VectorManager | None = None
    skill_manager: SkillManager | None = None
    plugin_manager: PluginManager | None = None
    plugin_host: PluginHostProtocol | None = None
    plugin_storage: PluginStorageProtocol | None = None
    plugin_assets: PluginAssetsProtocol | None = None
    plugin_python_environment_manager: PluginPythonEnvironmentManagerProtocol | None = (
        None
    )
    plugin_outbox: PluginOutboxProtocol | None = None
    plugin_task_scheduler: PluginTaskSchedulerProtocol | None = None
    tool_registry: ToolRegistryProtocol | None = None
    tool_manager: ToolManager | None = None
    tool_sandbox_runner: ToolSandboxRunnerProtocol | None = None
    bot_channel_registry: BotChannelRegistryProtocol | None = None
    bot_session_manager: BotSessionManager | None = None
    bot_polling_state_store: BotPollingStateStoreProtocol | None = None
    bot_admin_config: BotAdminConfig | None = None

    async def close(self) -> None:
        """
        关闭运行时持有的外部资源。
        """
        errors: list[Exception] = []

        if self.plugin_task_scheduler is not None:
            try:
                await self.plugin_task_scheduler.shutdown()
            except Exception as exc:
                errors.append(exc)

        try:
            await self.provider_manager.close_all()
        except Exception as exc:
            errors.append(exc)

        if self.provider_config_store is not None:
            try:
                await self.provider_config_store.close()
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

        if self.bot_polling_state_store is not None:
            try:
                await self.bot_polling_state_store.close()
            except Exception as exc:
                errors.append(exc)

        if self.plugin_storage is not None:
            try:
                await self.plugin_storage.close()
            except Exception as exc:
                errors.append(exc)

        if self.plugin_assets is not None:
            try:
                await self.plugin_assets.close()
            except Exception as exc:
                errors.append(exc)

        if errors:
            raise StateError(
                f"Failed to close {len(errors)} runtime resource(s)",
                cause=errors[0],
            )
