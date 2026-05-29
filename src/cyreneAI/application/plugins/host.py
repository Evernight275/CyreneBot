from __future__ import annotations

import logging

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
    PluginAssetsNamespaceProtocol,
    PluginEventExecutorProtocol,
    PluginLLMNamespaceProtocol,
    PluginLoaderProtocol,
    PluginModuleProtocol,
    PluginOutboxNamespaceProtocol,
    PluginRegistryProtocol,
    PluginRuntimeContextProtocol,
    PluginStorageNamespaceProtocol,
    PluginTaskExecutorProtocol,
    PluginTaskNamespaceProtocol,
)
from cyreneAI.core.schema.application import (
    ApplicationChatRequest,
    ApplicationChatResult,
    ApplicationImageGenerationRequest,
    ApplicationImageGenerationResult,
)
from cyreneAI.core.schema.message import ContentPart, ContentPartType, Message, MessageRole
from cyreneAI.core.schema.plugin import (
    PluginCapability,
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginDefinition,
    PluginEventDefinition,
    PluginEventRequest,
    PluginEventResult,
    PluginLifecycleStatus,
    PluginManifest,
    PluginPermission,
    PluginStatusReport,
    PluginTaskDefinition,
)
from cyreneAI.core.schema.provider import ProviderInfo, ProviderModel
from cyreneAI.core.schema.skill import SkillDefinition
from cyreneAI.core.schema.tool import ToolDefinition
from cyreneAI.core.skill.skill_protocol import SkillRegistryProtocol
from cyreneAI.core.tool.tool_protocol import ToolExecutorProtocol


logger = logging.getLogger(__name__)


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
        disabled_plugin_ids: set[str] | None = None,
        fail_fast: bool = True,
    ) -> None:
        self._runtime = runtime
        self._registry = registry
        self._skill_registry = skill_registry
        self._disabled_plugin_ids = set(disabled_plugin_ids or set())
        self._fail_fast = fail_fast

    def load(self, loader: PluginLoaderProtocol) -> list[PluginDefinition]:
        """
        从加载器加载并注册插件。
        """
        try:
            modules = loader.load()
        except PluginError as exc:
            status = PluginStatusReport(
                plugin_id=_loader_status_id(loader),
                status=PluginLifecycleStatus.FAILED,
                reason="loader_failed",
                error=str(exc),
            )
            self._registry.record_status(status)
            logger.exception(
                "Plugin loader failed: loader=%s",
                loader.__class__.__name__,
            )
            if not self._fail_fast:
                return []
            raise
        except Exception as exc:
            status = PluginStatusReport(
                plugin_id=_loader_status_id(loader),
                status=PluginLifecycleStatus.FAILED,
                reason="loader_failed",
                error=str(exc),
            )
            self._registry.record_status(status)
            logger.exception(
                "Plugin loader failed: loader=%s",
                loader.__class__.__name__,
            )
            if not self._fail_fast:
                return []
            raise PluginConfigurationError("插件加载失败", cause=exc) from exc

        definitions: list[PluginDefinition] = []
        for module in modules:
            try:
                definition = self.register(module)
            except PluginError:
                if self._fail_fast:
                    raise
                definition = None
            if definition is not None:
                definitions.append(definition)
        return definitions

    def register(self, module: PluginModuleProtocol) -> PluginDefinition | None:
        """
        注册一个插件入口模块。
        """
        manifest = module.manifest
        if not manifest.enabled or manifest.plugin_id in self._disabled_plugin_ids:
            reason = (
                "disabled_by_config"
                if manifest.plugin_id in self._disabled_plugin_ids
                else "disabled_by_manifest"
            )
            definition = manifest.to_definition().model_copy(
                update={"enabled": False}
            )
            self._registry.register(definition)
            self._registry.record_status(
                _status_from_manifest(
                    manifest,
                    status=PluginLifecycleStatus.DISABLED,
                    reason=reason,
                )
            )
            logger.info(
                "Plugin disabled: plugin_id=%s reason=%s",
                manifest.plugin_id,
                reason,
            )
            return definition

        runtime_context = ApplicationPluginRuntimeContext(
            runtime=self._runtime,
            plugin_id=manifest.plugin_id,
            permissions=set(manifest.permissions),
        )
        setup_context = ApplicationPluginSetupContext(
            manifest=manifest,
            runtime_context=runtime_context,
            runtime=self._runtime,
            skill_registry=self._skill_registry,
        )

        try:
            self._registry.record_status(
                _status_from_manifest(
                    manifest,
                    status=PluginLifecycleStatus.LOADED,
                    reason="setup_started",
                )
            )
            module.setup(setup_context)
        except PluginError as exc:
            self._registry.record_status(
                _status_from_manifest(
                    manifest,
                    status=PluginLifecycleStatus.FAILED,
                    reason="setup_failed",
                    error=str(exc),
                )
            )
            logger.exception(
                "Plugin setup failed: plugin_id=%s",
                manifest.plugin_id,
            )
            raise
        except Exception as exc:
            self._registry.record_status(
                _status_from_manifest(
                    manifest,
                    status=PluginLifecycleStatus.FAILED,
                    reason="setup_failed",
                    error=str(exc),
                )
            )
            logger.exception(
                "Plugin setup failed: plugin_id=%s",
                manifest.plugin_id,
            )
            raise PluginConfigurationError(
                f"插件 {manifest.plugin_id} setup 失败",
                cause=exc,
            ) from exc

        definition = setup_context.build_definition()
        command_executor, event_executor = setup_context.build_executors()
        self._registry.register(
            definition,
            command_executor,
            event_executor=event_executor,
        )
        return definition


class ApplicationPluginRuntimeContext:
    """
    application 暴露给第三方插件的受控运行时上下文。
    """

    def __init__(
        self,
        *,
        runtime: CyreneAIRuntime,
        plugin_id: str,
        permissions: set[PluginPermission],
    ) -> None:
        self._runtime = runtime
        self._plugin_id = plugin_id
        self._permissions = permissions
        self._chat_orchestrator = ChatOrchestrator(runtime)
        self._image_orchestrator = ImageGenerationOrchestrator(runtime)

    def require_permission(self, permission: PluginPermission) -> None:
        if permission not in self._permissions:
            raise PluginAuthorizationError(f"插件缺少权限: {permission}")

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

    @property
    def llm(self) -> PluginLLMNamespaceProtocol:
        self.require_permission(PluginPermission.LLM)
        return ApplicationPluginLLMNamespace(
            chat_orchestrator=self._chat_orchestrator,
            plugin_id=self._plugin_id,
        )

    def llm_for_request(
        self,
        request: PluginCommandRequest | PluginTaskRequest | PluginEventRequest,
    ) -> PluginLLMNamespaceProtocol:
        self.require_permission(PluginPermission.LLM)
        return ApplicationPluginLLMNamespace(
            chat_orchestrator=self._chat_orchestrator,
            plugin_id=self._plugin_id,
            default_provider_id=_request_metadata_str(request, "provider_id"),
            default_model=_request_metadata_str(request, "model"),
            default_session_id=_request_session_id(request),
            default_metadata=dict(request.metadata),
        )

    @property
    def storage(self) -> PluginStorageNamespaceProtocol:
        self.require_permission(PluginPermission.STORAGE)
        if self._runtime.plugin_storage is None:
            raise PluginStateError("runtime 未配置 plugin storage")
        return self._runtime.plugin_storage.namespace(self._plugin_id)

    @property
    def assets(self) -> PluginAssetsNamespaceProtocol:
        self.require_permission(PluginPermission.ASSETS)
        if self._runtime.plugin_assets is None:
            raise PluginStateError("runtime 未配置 plugin assets")
        return self._runtime.plugin_assets.namespace(self._plugin_id)

    @property
    def tasks(self) -> PluginTaskNamespaceProtocol:
        self.require_permission(PluginPermission.TASK)
        if self._runtime.plugin_task_scheduler is None:
            raise PluginStateError("runtime 未配置 plugin task scheduler")
        return self._runtime.plugin_task_scheduler.namespace(self._plugin_id)

    @property
    def messages(self) -> PluginOutboxNamespaceProtocol:
        self.require_permission(PluginPermission.MESSAGE_SEND)
        if self._runtime.plugin_outbox is None:
            raise PluginStateError("runtime 未配置 plugin outbox")
        return self._runtime.plugin_outbox.namespace(
            self._plugin_id,
            can_bypass_rate_limit=(
                PluginPermission.MESSAGE_SEND_UNLIMITED in self._permissions
            ),
        )

    @property
    def outbox(self) -> PluginOutboxNamespaceProtocol:
        return self.messages


class ApplicationPluginLLMNamespace:
    """
    application 暴露给插件的受控 LLM 命名空间。
    """

    def __init__(
        self,
        *,
        chat_orchestrator: ChatOrchestrator,
        plugin_id: str,
        default_provider_id: str | None = None,
        default_model: str | None = None,
        default_session_id: str | None = None,
        default_metadata: dict[str, object] | None = None,
    ) -> None:
        self._chat_orchestrator = chat_orchestrator
        self._plugin_id = plugin_id
        self._default_provider_id = default_provider_id
        self._default_model = default_model
        self._default_session_id = default_session_id
        self._default_metadata = default_metadata or {}

    async def chat(
        self,
        prompt: str,
        *,
        provider_id: str | None = None,
        model: str | None = None,
        system: str | None = None,
        session_id: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> str:
        result = await self.result(
            prompt,
            provider_id=provider_id,
            model=model,
            system=system,
            session_id=session_id,
            temperature=temperature,
            max_tokens=max_tokens,
            metadata=metadata,
        )
        return _chat_result_text(result)

    async def result(
        self,
        prompt: str,
        *,
        provider_id: str | None = None,
        model: str | None = None,
        system: str | None = None,
        session_id: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ApplicationChatResult:
        resolved_provider_id = provider_id or self._default_provider_id
        resolved_model = model or self._default_model
        if not resolved_provider_id or not resolved_model:
            raise PluginConfigurationError(
                "llm.chat requires provider_id and model when no bot defaults are available"
            )

        messages: list[Message] = []
        if system:
            messages.append(_text_message(MessageRole.SYSTEM, system))
        messages.append(_text_message(MessageRole.USER, prompt))
        return await self._chat_orchestrator.chat(
            ApplicationChatRequest(
                session_id=session_id
                or self._default_session_id
                or f"plugin:{self._plugin_id}",
                provider_id=resolved_provider_id,
                model=resolved_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                metadata={
                    **self._default_metadata,
                    **(metadata or {}),
                    "plugin_id": self._plugin_id,
                },
            )
        )


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
        self._tasks: list[PluginTaskDefinition] = list(manifest.tasks)
        self._events: list[PluginEventDefinition] = list(manifest.events)
        self._command_executors: dict[str, PluginExecutorProtocol] = {}
        self._event_executors: dict[str, PluginEventExecutorProtocol] = {}
        self._task_executor_names: set[str] = set()
        self._event_executor_names: set[str] = set()

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

    def register_task(
        self,
        definition: PluginTaskDefinition,
        executor: PluginTaskExecutorProtocol,
    ) -> None:
        self._ensure_capability(PluginCapability.TASK)
        if self._runtime.plugin_task_scheduler is None:
            raise PluginStateError("runtime 未配置 plugin task scheduler")
        self._register_task_definition(definition)
        self._runtime.plugin_task_scheduler.register_task(
            self._manifest.plugin_id,
            definition,
            executor,
        )
        self._task_executor_names.add(_normalize_task_name(definition.name))

    def register_event(
        self,
        definition: PluginEventDefinition,
        executor: PluginEventExecutorProtocol,
    ) -> None:
        self._ensure_capability(PluginCapability.EVENT)
        self._register_event_definition(definition)
        event_name = _normalize_event_type(definition.event_type)
        if event_name in self._event_executor_names:
            raise PluginConfigurationError(f"插件事件 {event_name} 重复注册")
        self._event_executor_names.add(event_name)
        self._event_executors[event_name] = executor

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
        for task in self._tasks:
            if _normalize_task_name(task.name) not in self._task_executor_names:
                raise PluginConfigurationError(
                    f"插件任务 {task.name} 未注册执行器"
                )
        for event in self._events:
            if _normalize_event_type(event.event_type) not in self._event_executor_names:
                raise PluginConfigurationError(
                    f"插件事件 {event.event_type} 未注册执行器"
                )
        return definition.model_copy(
            update={
                "commands": list(self._commands),
                "tasks": list(self._tasks),
                "events": list(self._events),
            }
        )

    def build_executors(
        self,
    ) -> tuple[PluginExecutorProtocol | None, PluginEventExecutorProtocol | None]:
        command_executor: PluginExecutorProtocol | None = None
        if not self._commands:
            command_executor = None
        else:
            for command in self._commands:
                if not any(
                    command_name in self._command_executors
                    for command_name in _command_names(command)
                ):
                    raise PluginConfigurationError(
                        f"插件命令 {command.name} 未注册执行器"
                    )
            command_executor = _PluginCommandRouter(self._command_executors)

        event_executor: PluginEventExecutorProtocol | None = None
        if self._events:
            event_executor = _PluginEventRouter(self._event_executors)
        return command_executor, event_executor

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

    def _register_task_definition(
        self,
        definition: PluginTaskDefinition,
    ) -> None:
        existing_names = {_normalize_task_name(task.name) for task in self._tasks}
        definition_name = _normalize_task_name(definition.name)
        if definition_name in existing_names:
            return
        self._tasks.append(definition)

    def _register_event_definition(
        self,
        definition: PluginEventDefinition,
    ) -> None:
        existing_names = {_normalize_event_type(event.event_type) for event in self._events}
        definition_name = _normalize_event_type(definition.event_type)
        if definition_name in existing_names:
            return
        self._events.append(definition)


class _PluginCommandRouter:
    def __init__(self, executors: dict[str, PluginExecutorProtocol]) -> None:
        self._executors = executors

    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        executor = self._executors.get(_normalize_command_name(request.command.name))
        if executor is None:
            raise PluginNotFoundError(f"插件命令 {request.command.name} 不存在")
        return await executor.execute(request)


class _PluginEventRouter:
    def __init__(self, executors: dict[str, PluginEventExecutorProtocol]) -> None:
        self._executors = executors

    async def execute(self, request: PluginEventRequest) -> PluginEventResult:
        event_name = _normalize_event_type(request.route.event_type)
        executor = self._executors.get(event_name)
        if executor is None:
            raise PluginNotFoundError(f"插件事件 {event_name} 不存在")
        return await executor.execute(request)


def _command_names(definition: PluginCommandDefinition) -> set[str]:
    names = {_normalize_command_name(definition.name)}
    names.update(_normalize_command_name(alias) for alias in definition.aliases)
    return {name for name in names if name}


def _normalize_command_name(name: str) -> str:
    return name.strip().lower().removeprefix("/")


def _normalize_task_name(name: str) -> str:
    return " ".join(name.strip().replace("/", " ").split()).lower()


def _normalize_event_type(event_type: object) -> str:
    return str(event_type).strip().lower()


def _text_message(role: MessageRole, text: str) -> Message:
    return Message(
        role=role,
        content=[
            ContentPart(
                type=ContentPartType.TEXT,
                text=text,
            )
        ],
    )


def _chat_result_text(result: ApplicationChatResult) -> str:
    message = result.response.message
    if message is None or not message.content:
        return ""
    return "".join(
        part.text or ""
        for part in message.content
        if part.type == ContentPartType.TEXT
    )


def _request_metadata_str(
    request: PluginCommandRequest | PluginTaskRequest | PluginEventRequest,
    key: str,
) -> str | None:
    value = request.metadata.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _request_session_id(
    request: PluginCommandRequest | PluginTaskRequest | PluginEventRequest,
) -> str | None:
    if isinstance(request, PluginCommandRequest) and request.event is not None:
        return request.event.session_id
    if isinstance(request, PluginEventRequest):
        return request.event.session_id
    return _request_metadata_str(request, "session_id")


def _status_from_manifest(
    manifest: PluginManifest,
    *,
    status: PluginLifecycleStatus,
    reason: str | None = None,
    error: str | None = None,
) -> PluginStatusReport:
    return PluginStatusReport(
        plugin_id=manifest.plugin_id,
        status=status,
        enabled=status == PluginLifecycleStatus.ENABLED,
        name=manifest.name,
        version=manifest.version,
        reason=reason,
        error=error,
    )


def _loader_status_id(loader: PluginLoaderProtocol) -> str:
    return f"loader:{loader.__class__.__module__}.{loader.__class__.__name__}"
