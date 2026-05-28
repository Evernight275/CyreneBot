from __future__ import annotations

from typing import Protocol

from cyreneAI.core.schema.application import (
    ApplicationChatRequest,
    ApplicationChatResult,
    ApplicationImageGenerationRequest,
    ApplicationImageGenerationResult,
)
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginDefinition,
    PluginManifest,
    PluginPermission,
)
from cyreneAI.core.schema.provider import ProviderInfo, ProviderModel
from cyreneAI.core.schema.skill import SkillDefinition
from cyreneAI.core.schema.tool import ToolDefinition
from cyreneAI.core.tool.tool_protocol import ToolExecutorProtocol


class PluginExecutorProtocol(Protocol):
    """
    插件命令执行器协议。
    """

    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        """
        执行插件命令。
        """
        ...


class PluginRuntimeContextProtocol(Protocol):
    """
    第三方插件运行时上下文协议。
    """

    def require_permission(self, permission: PluginPermission) -> None:
        """
        要求插件具备指定权限。
        """
        ...

    async def chat(self, request: ApplicationChatRequest) -> ApplicationChatResult:
        """
        调用应用聊天能力。
        """
        ...

    async def generate_image(
        self,
        request: ApplicationImageGenerationRequest,
    ) -> ApplicationImageGenerationResult:
        """
        调用应用生图能力。
        """
        ...

    def list_providers(self) -> list[ProviderInfo]:
        """
        列出运行中的 provider。
        """
        ...

    async def list_provider_models(self, provider_id: str) -> list[ProviderModel]:
        """
        列出 provider 模型。
        """
        ...


class PluginSetupContextProtocol(Protocol):
    """
    第三方插件 setup 阶段上下文协议。
    """

    @property
    def manifest(self) -> PluginManifest:
        """
        当前插件清单。
        """
        ...

    @property
    def runtime(self) -> PluginRuntimeContextProtocol:
        """
        受控运行时上下文。
        """
        ...

    def register_command(
        self,
        definition: PluginCommandDefinition,
        executor: PluginExecutorProtocol,
    ) -> None:
        """
        注册 bot 命令。
        """
        ...

    def register_tool(
        self,
        definition: ToolDefinition,
        executor: ToolExecutorProtocol,
    ) -> None:
        """
        注册工具。
        """
        ...

    def register_skill(self, definition: SkillDefinition) -> None:
        """
        注册技能。
        """
        ...


class PluginModuleProtocol(Protocol):
    """
    第三方插件入口模块协议。
    """

    manifest: PluginManifest

    def setup(self, context: PluginSetupContextProtocol) -> None:
        """
        注册插件能力。
        """
        ...


class PluginLoaderProtocol(Protocol):
    """
    插件加载器协议。
    """

    def load(self) -> list[PluginModuleProtocol]:
        """
        加载插件入口模块。
        """
        ...


class PluginRegistryProtocol(Protocol):
    """
    插件注册器协议。
    """

    def register(
        self,
        definition: PluginDefinition,
        executor: PluginExecutorProtocol | None = None,
    ) -> None:
        """
        注册插件。
        """
        ...

    def unregister(self, plugin_id: str) -> None:
        """
        注销插件。
        """
        ...

    def get_definition(self, plugin_id: str) -> PluginDefinition:
        """
        获取插件定义。
        """
        ...

    def get_executor(self, plugin_id: str) -> PluginExecutorProtocol:
        """
        获取插件执行器。
        """
        ...

    def exists(self, plugin_id: str) -> bool:
        """
        判断插件是否存在。
        """
        ...

    def list_definitions(self) -> list[PluginDefinition]:
        """
        列出插件定义。
        """
        ...

    def list_commands(self) -> list[PluginCommandDefinition]:
        """
        列出已启用命令定义。
        """
        ...

    def resolve_command(
        self,
        command_name: str,
    ) -> tuple[PluginDefinition, PluginCommandDefinition, PluginExecutorProtocol]:
        """
        根据命令名解析插件定义、命令定义与执行器。
        """
        ...
