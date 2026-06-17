from __future__ import annotations

from typing import Protocol

from cyreneAI.core.bot.bot_protocol import BotChannelRegistryProtocol
from cyreneAI.core.bot.polling_protocol import BotPollingStateStoreProtocol
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.context.context_protocol import ContextBuilderProtocol
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.plugin.manager import PluginManager
from cyreneAI.core.plugin.plugin_protocol import (
    PluginAssetsProtocol,
    PluginDefinition,
    PluginLoaderProtocol,
    PluginOutboxProtocol,
    PluginPythonEnvironmentManagerProtocol,
    PluginStorageProtocol,
    PluginTaskSchedulerProtocol,
)
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.provider.provider_protocol import ProviderConfigStoreProtocol
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.application import BotAdminConfig
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.tool_protocol import (
    ToolRegistryProtocol,
    ToolSandboxRunnerProtocol,
)
from cyreneAI.core.vector.manager import VectorManager


class PluginHostProtocol(Protocol):
    """
    插件宿主协议。

    这是 runtime 暴露的插件装载/重载能力契约；具体宿主实现属于
    application，core 只定义它在运行态中应当呈现的形状。
    """

    def load(self, loader: PluginLoaderProtocol) -> list[PluginDefinition]:
        """
        从加载器加载并注册插件。
        """
        ...

    def reload(self, plugin_id: str) -> PluginDefinition:
        """
        从已记录来源重新加载插件。
        """
        ...


class CyreneAIRuntimeProtocol(Protocol):
    """
    CyreneAI 运行态协议。

    runtime 是 bootstrap 完成总装之后交给 application/server 使用的能力账本。
    core 在这里定义运行态应当公开哪些受管能力；具体容器实现由
    application.runtime 提供。
    """

    provider_manager: ProviderManager
    context_builder: ContextBuilderProtocol
    provider_registry: ProviderRegistry | None
    provider_config_store: ProviderConfigStoreProtocol | None
    context_manager: ContextManager | None
    vector_manager: VectorManager | None
    plugin_manager: PluginManager | None
    plugin_host: PluginHostProtocol | None
    plugin_storage: PluginStorageProtocol | None
    plugin_assets: PluginAssetsProtocol | None
    plugin_python_environment_manager: PluginPythonEnvironmentManagerProtocol | None
    plugin_outbox: PluginOutboxProtocol | None
    plugin_task_scheduler: PluginTaskSchedulerProtocol | None
    tool_registry: ToolRegistryProtocol | None
    tool_manager: ToolManager | None
    tool_sandbox_runner: ToolSandboxRunnerProtocol | None
    bot_channel_registry: BotChannelRegistryProtocol | None
    bot_session_manager: BotSessionManager | None
    bot_polling_state_store: BotPollingStateStoreProtocol | None
    bot_admin_config: BotAdminConfig | None

    async def close(self) -> None:
        """
        关闭运行态持有的受管资源。
        """
        ...
