from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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
    PluginTaskSchedulerProtocol,
    PluginStorageProtocol,
)
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.skill.manager import SkillManager
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.tool_protocol import (
    ToolRegistryProtocol,
    ToolSandboxRunnerProtocol,
)
from cyreneAI.core.vector.manager import VectorManager

if TYPE_CHECKING:
    from cyreneAI.application.plugins.host import PluginHost


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
    plugin_manager: PluginManager | None = None
    plugin_host: PluginHost | None = None
    plugin_storage: PluginStorageProtocol | None = None
    plugin_assets: PluginAssetsProtocol | None = None
    plugin_outbox: PluginOutboxProtocol | None = None
    plugin_task_scheduler: PluginTaskSchedulerProtocol | None = None
    tool_registry: ToolRegistryProtocol | None = None
    tool_manager: ToolManager | None = None
    tool_sandbox_runner: ToolSandboxRunnerProtocol | None = None
    bot_channel_registry: BotChannelRegistryProtocol | None = None
    bot_session_manager: BotSessionManager | None = None
    bot_polling_state_store: BotPollingStateStoreProtocol | None = None

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
