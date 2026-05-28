from __future__ import annotations

from cyreneAI.application.chat.orchestrator import ChatOrchestrator
from cyreneAI.application.generation.image_orchestrator import ImageGenerationOrchestrator
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.plugin import (
    PluginAuthorizationError,
    PluginConfigurationError,
    PluginError,
    PluginNotFoundError,
    PluginStateError,
)
from cyreneAI.core.plugin.plugin_protocol import (
    PluginExecutorProtocol,
    PluginLoaderProtocol,
    PluginModuleProtocol,
    PluginRegistryProtocol,
    PluginRuntimeContextProtocol,
)
from cyreneAI.core.schema.application import (
    ApplicationChatRequest,
    ApplicationChatResult,
    ApplicationImageGenerationRequest,
    ApplicationImageGenerationResult,
)
from cyreneAI.core.schema.plugin import (
    PluginCapability,
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
from cyreneAI.core.skill.skill_protocol import SkillRegistryProtocol
from cyreneAI.core.tool.tool_protocol import ToolExecutorProtocol


class PluginHost:
    """
    第三方插件宿主。
    """

    def __init__(
        self,
        *,
        runtime: CyreneAIRuntime,
        registry: PluginRegistryProtocol,
        skill_registry: SkillRegistryProtocol | None = None,
    ) -> None:
        self._runtime = runtime
        self._registry = registry
        self._skill_registry = skill_registry

    def load(self, loader: PluginLoaderProtocol) -> list[PluginDefinition]:
        """
        从加载器加载并注册插件。
        """
        try:
            modules = loader.load()
        except PluginError:
            raise
        except Exception as exc:
            raise PluginConfigurationError("插件加载失败", cause=exc) from exc

        definitions: list[PluginDefinition] = []
        for module in modules:
            definition = self.register(module)
            if definition is not None:
                definitions.append(definition)
        return definitions

    def register(self, module: PluginModuleProtocol) -> PluginDefinition | None:
        """
        注册一个插件入口模块。
        """
        manifest = module.manifest
        if not manifest.enabled:
            return None

        runtime_context = ApplicationPluginRuntimeContext(
            runtime=self._runtime,
            permissions=set(manifest.permissions),
        )
        setup_context = ApplicationPluginSetupContext(
            manifest=manifest,
            runtime_context=runtime_context,
            runtime=self._runtime,
            skill_registry=self._skill_registry,
        )

        try:
            module.setup(setup_context)
        except PluginError:
            raise
        except Exception as exc:
            raise PluginConfigurationError(
                f"插件 {manifest.plugin_id} setup 失败",
                cause=exc,
            ) from exc

        definition = setup_context.build_definition()
        executor = setup_context.build_executor()
        self._registry.register(definition, executor)
        return definition


class ApplicationPluginRuntimeContext:
    """
    application 暴露给第三方插件的受控运行时上下文。
    """

    def __init__(
        self,
        *,
        runtime: CyreneAIRuntime,
        permissions: set[PluginPermission],
    ) -> None:
        self._runtime = runtime
        self._permissions = permissions
        self._chat_orchestrator = ChatOrchestrator(runtime)
        self._image_orchestrator = ImageGenerationOrchestrator(runtime)

    def require_permission(self, permission: PluginPermission) -> None:
        if permission not in self._permissions:
            raise PluginAuthorizationError(f"插件缺少权限: {permission}")

    async def chat(self, request: ApplicationChatRequest) -> ApplicationChatResult:
        self.require_permission(PluginPermission.CHAT)
        return await self._chat_orchestrator.chat(request)

    async def generate_image(
        self,
        request: ApplicationImageGenerationRequest,
    ) -> ApplicationImageGenerationResult:
        self.require_permission(PluginPermission.IMAGE)
        return await self._image_orchestrator.generate_image(request)

    def list_providers(self) -> list[ProviderInfo]:
        self.require_permission(PluginPermission.PROVIDER_READ)
        return self._runtime.provider_manager.list_running()

    async def list_provider_models(self, provider_id: str) -> list[ProviderModel]:
        self.require_permission(PluginPermission.PROVIDER_READ)
        return await self._runtime.provider_manager.list_models(provider_id)


class ApplicationPluginSetupContext:
    """
    application 提供给第三方插件 setup 的注册上下文。
    """

    def __init__(
        self,
        *,
        manifest: PluginManifest,
        runtime_context: PluginRuntimeContextProtocol,
        runtime: CyreneAIRuntime,
        skill_registry: SkillRegistryProtocol | None = None,
    ) -> None:
        self._manifest = manifest
        self._runtime_context = runtime_context
        self._runtime = runtime
        self._skill_registry = skill_registry
        self._commands: list[PluginCommandDefinition] = list(manifest.commands)
        self._command_executors: dict[str, PluginExecutorProtocol] = {}

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    @property
    def runtime(self) -> PluginRuntimeContextProtocol:
        return self._runtime_context

    def register_command(
        self,
        definition: PluginCommandDefinition,
        executor: PluginExecutorProtocol,
    ) -> None:
        self._ensure_capability(PluginCapability.BOT_COMMAND)
        self._register_command_definition(definition)
        for command_name in _command_names(definition):
            if command_name in self._command_executors:
                raise PluginConfigurationError(f"插件命令 {command_name} 重复注册")
            self._command_executors[command_name] = executor

    def register_tool(
        self,
        definition: ToolDefinition,
        executor: ToolExecutorProtocol,
    ) -> None:
        self._runtime_context.require_permission(PluginPermission.TOOL)
        self._ensure_capability(PluginCapability.TOOL)
        if self._runtime.tool_registry is None:
            raise PluginStateError("runtime 未配置 tool registry")
        self._runtime.tool_registry.register(definition, executor)

    def register_skill(self, definition: SkillDefinition) -> None:
        self._runtime_context.require_permission(PluginPermission.SKILL)
        self._ensure_capability(PluginCapability.SKILL)
        if self._skill_registry is None:
            raise PluginStateError("runtime 未配置 skill registry")
        self._skill_registry.register(definition)

    def build_definition(self) -> PluginDefinition:
        definition = self._manifest.to_definition()
        return definition.model_copy(update={"commands": list(self._commands)})

    def build_executor(self) -> PluginExecutorProtocol | None:
        if not self._commands:
            return None
        for command in self._commands:
            if not any(
                command_name in self._command_executors
                for command_name in _command_names(command)
            ):
                raise PluginConfigurationError(
                    f"插件命令 {command.name} 未注册执行器"
                )
        return _PluginCommandRouter(self._command_executors)

    def _ensure_capability(self, capability: PluginCapability) -> None:
        if capability not in self._manifest.capabilities:
            raise PluginConfigurationError(f"插件未声明能力: {capability}")

    def _register_command_definition(
        self,
        definition: PluginCommandDefinition,
    ) -> None:
        existing_names: set[str] = set()
        for command in self._commands:
            existing_names.update(_command_names(command))

        definition_names = _command_names(definition)
        if definition_names and definition_names.issubset(existing_names):
            return

        for command_name in definition_names:
            if command_name in existing_names:
                raise PluginConfigurationError(f"插件命令 {command_name} 重复声明")
        self._commands.append(definition)


class _PluginCommandRouter:
    def __init__(self, executors: dict[str, PluginExecutorProtocol]) -> None:
        self._executors = executors

    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        executor = self._executors.get(_normalize_command_name(request.command.name))
        if executor is None:
            raise PluginNotFoundError(f"插件命令 {request.command.name} 不存在")
        return await executor.execute(request)


def _command_names(definition: PluginCommandDefinition) -> set[str]:
    names = {_normalize_command_name(definition.name)}
    names.update(_normalize_command_name(alias) for alias in definition.aliases)
    return {name for name in names if name}


def _normalize_command_name(name: str) -> str:
    return name.strip().lower().removeprefix("/")
