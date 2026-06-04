from __future__ import annotations

import logging
import uuid
from contextlib import suppress
from datetime import UTC, datetime

from cyreneAI.application.agent.orchestrator import AgentOrchestrator
from cyreneAI.application.agent.request_builder import build_agent_run_request
from cyreneAI.application.chat.orchestrator import ChatOrchestrator
from cyreneAI.application.generation.image_orchestrator import (
    ImageGenerationOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.plugin import (
    PluginAuthorizationError,
    PluginConfigurationError,
    PluginError,
    PluginNotFoundError,
    PluginStateError,
)
from cyreneAI.core.plugin.install_policy import PluginInstallPolicy
from cyreneAI.core.plugin.plugin_protocol import (
    PluginAssetsNamespaceProtocol,
    PluginEventExecutorProtocol,
    PluginExecutorProtocol,
    PluginLLMNamespaceProtocol,
    PluginLoaderProtocol,
    PluginMiddlewareExecutorProtocol,
    PluginModuleProtocol,
    PluginOutboxNamespaceProtocol,
    PluginRegistryProtocol,
    PluginReloadableSourceProtocol,
    PluginRuntimeContextProtocol,
    PluginStorageNamespaceProtocol,
    PluginTaskExecutorProtocol,
    PluginTaskNamespaceProtocol,
)
from cyreneAI.core.schema.agent import (
    AgentMemoryRetrievalConfig,
    AgentPlanningConfig,
    AgentRunResult,
    AgentToolSelectionConfig,
)
from cyreneAI.core.schema.application import (
    ApplicationChatRequest,
    ApplicationChatResult,
    ApplicationImageGenerationRequest,
    ApplicationImageGenerationResult,
)
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
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
    PluginMiddlewareDefinition,
    PluginMiddlewareRequest,
    PluginPermission,
    PluginPermissionAuditDecision,
    PluginPermissionAuditRecord,
    PluginSourceInfo,
    PluginStatusReport,
    PluginTaskDefinition,
    PluginTaskRequest,
)
from cyreneAI.core.schema.provider import ProviderInfo, ProviderModel
from cyreneAI.core.schema.skill import SkillDefinition
from cyreneAI.core.schema.tool import ToolChoice, ToolDefinition, ToolExecutionPolicy
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
        self._modules: dict[str, PluginModuleProtocol] = {}
        self._reloaders: dict[str, PluginReloadableSourceProtocol] = {}
        self._plugin_tool_names: dict[str, set[str]] = {}
        self._plugin_skill_names: dict[str, set[str]] = {}

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
                commands=[],
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
                commands=[],
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
            except (PluginError, ConflictError):
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
            definition = manifest.to_definition().model_copy(update={"enabled": False})
            self._registry.register(definition)
            self._remember_module_metadata(module, definition)
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
        command_executor, event_executor, middleware_executor = (
            setup_context.build_executors()
        )
        # 先记录 setup 已注册的运行时资源名，确保后续注册失败时也能回收。
        self._plugin_tool_names[definition.plugin_id] = setup_context.tool_names
        self._plugin_skill_names[definition.plugin_id] = setup_context.skill_names
        try:
            self._registry.register(
                definition,
                command_executor,
                event_executor=event_executor,
                middleware_executor=middleware_executor,
            )
        except ConflictError as exc:
            self._handle_register_failure(
                manifest,
                definition.plugin_id,
                reason="register_conflict",
                error=str(exc),
            )
            raise
        except Exception as exc:
            self._handle_register_failure(
                manifest,
                definition.plugin_id,
                reason="register_failed",
                error=str(exc),
            )
            raise PluginConfigurationError(
                f"插件 {definition.plugin_id} 注册失败",
                cause=exc,
            ) from exc
        self._remember_module_metadata(module, definition)
        return definition

    def _handle_register_failure(
        self,
        manifest: PluginManifest,
        plugin_id: str,
        *,
        reason: str,
        error: str,
    ) -> None:
        """
        注册失败时回收 setup 已注册的运行时资源并记录 FAILED 状态。
        """
        self._unregister_runtime_resources(plugin_id)
        self._registry.record_status(
            _status_from_manifest(
                manifest,
                status=PluginLifecycleStatus.FAILED,
                reason=reason,
                error=error,
            )
        )
        logger.exception(
            "Plugin register failed: plugin_id=%s reason=%s",
            plugin_id,
            reason,
        )

    def reload(self, plugin_id: str) -> PluginDefinition:
        """
        从已记录来源重新加载插件，并尽量在失败时恢复旧插件。
        """
        old_definition = self._registry.get_definition(plugin_id)
        source = self._registry.get_source(plugin_id)
        reloader = self._reloaders.get(plugin_id)
        old_module = self._modules.get(plugin_id)
        if reloader is None or old_module is None:
            raise PluginStateError(f"插件 {plugin_id} 未配置可 reload 来源")

        new_module = reloader.reload_plugin(source)
        new_manifest = new_module.manifest
        if new_manifest.plugin_id != plugin_id:
            raise PluginConfigurationError(
                f"插件 reload 后的 plugin_id 不匹配: {new_manifest.plugin_id}"
            )
        new_source = _module_source(new_module, plugin_id)
        reload_audit = PluginInstallPolicy().validate_reload(
            plugin_id=plugin_id,
            old_definition=old_definition,
            old_source=source,
            new_manifest=new_manifest,
            new_source=new_source,
        )
        new_source.metadata["reload_audit"] = reload_audit

        self._unregister_plugin(plugin_id)
        try:
            definition = self.register(new_module)
            if definition is None:
                raise PluginStateError(f"插件 {plugin_id} reload 后未注册")
            if not old_definition.enabled and definition.enabled:
                definition = self._registry.set_enabled(plugin_id, False)
            self._registry.record_status(
                PluginStatusReport(
                    plugin_id=definition.plugin_id,
                    status=(
                        PluginLifecycleStatus.ENABLED
                        if definition.enabled
                        else PluginLifecycleStatus.DISABLED
                    ),
                    enabled=definition.enabled,
                    name=definition.name,
                    version=definition.version,
                    reason="reloaded",
                    commands=list(definition.commands),
                )
            )
            return definition
        except Exception:
            logger.exception("Plugin reload failed: plugin_id=%s", plugin_id)
            self._unregister_plugin(plugin_id, missing_ok=True)
            try:
                restored = self.register(old_module)
                if (
                    restored is not None
                    and not old_definition.enabled
                    and restored.enabled
                ):
                    self._registry.set_enabled(plugin_id, False)
            except Exception:
                logger.exception(
                    "Plugin reload rollback failed: plugin_id=%s", plugin_id
                )
            raise

    def _remember_module_metadata(
        self,
        module: PluginModuleProtocol,
        definition: PluginDefinition,
    ) -> None:
        self._modules[definition.plugin_id] = module
        source = getattr(module, "__cyreneai_plugin_source__", None)
        if source is not None:
            self._registry.record_source(source)
        reloader = getattr(module, "__cyreneai_plugin_reloader__", None)
        if reloader is not None and callable(getattr(reloader, "reload_plugin", None)):
            self._reloaders[definition.plugin_id] = reloader

    def _unregister_plugin(self, plugin_id: str, *, missing_ok: bool = False) -> None:
        self._unregister_runtime_resources(plugin_id)
        if self._registry.exists(plugin_id):
            self._registry.unregister(plugin_id)
        elif not missing_ok:
            raise PluginNotFoundError(f"该插件 {plugin_id} 不存在")
        self._modules.pop(plugin_id, None)
        self._reloaders.pop(plugin_id, None)

    def _unregister_runtime_resources(self, plugin_id: str) -> None:
        if self._runtime.plugin_task_scheduler is not None:
            self._runtime.plugin_task_scheduler.unregister_plugin(plugin_id)
        if self._runtime.tool_registry is not None:
            for name in self._plugin_tool_names.pop(plugin_id, set()):
                with suppress(Exception):
                    self._runtime.tool_registry.unregister(name)
        if self._skill_registry is not None:
            for name in self._plugin_skill_names.pop(plugin_id, set()):
                with suppress(Exception):
                    self._skill_registry.unregister(name)


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
        self._agent_orchestrator = AgentOrchestrator(runtime)
        self._image_orchestrator = ImageGenerationOrchestrator(runtime)

    def require_permission(self, permission: PluginPermission) -> None:
        allowed = permission in self._permissions
        self._record_permission_audit(
            permission,
            (
                PluginPermissionAuditDecision.ALLOWED
                if allowed
                else PluginPermissionAuditDecision.DENIED
            ),
        )
        if not allowed:
            raise PluginAuthorizationError(f"插件缺少权限: {permission}")

    def _record_permission_audit(
        self,
        permission: PluginPermission,
        decision: PluginPermissionAuditDecision,
    ) -> None:
        if self._runtime.plugin_manager is None:
            return
        self._runtime.plugin_manager.record_permission_audit(
            PluginPermissionAuditRecord(
                audit_id=uuid.uuid4().hex,
                plugin_id=self._plugin_id,
                permission=permission,
                decision=decision,
                reason=(
                    None
                    if decision == PluginPermissionAuditDecision.ALLOWED
                    else "missing_permission"
                ),
                created_at=datetime.now(UTC),
            )
        )

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
        request: (
            PluginCommandRequest
            | PluginTaskRequest
            | PluginEventRequest
            | PluginMiddlewareRequest
        ),
    ) -> PluginLLMNamespaceProtocol:
        self.require_permission(PluginPermission.LLM)
        return ApplicationPluginLLMNamespace(
            chat_orchestrator=self._chat_orchestrator,
            plugin_id=self._plugin_id,
            default_provider_id=_request_metadata_str(request, "provider_id"),
            default_model=_request_metadata_str(request, "model"),
            default_session_id=_request_session_id(request),
            default_metadata=_request_metadata(request),
        )

    @property
    def agent(self) -> "ApplicationPluginAgentNamespace":
        self.require_permission(PluginPermission.LLM)
        return ApplicationPluginAgentNamespace(
            agent_orchestrator=self._agent_orchestrator,
            plugin_id=self._plugin_id,
        )

    def agent_for_request(
        self,
        request: (
            PluginCommandRequest
            | PluginTaskRequest
            | PluginEventRequest
            | PluginMiddlewareRequest
        ),
    ) -> "ApplicationPluginAgentNamespace":
        self.require_permission(PluginPermission.LLM)
        return ApplicationPluginAgentNamespace(
            agent_orchestrator=self._agent_orchestrator,
            plugin_id=self._plugin_id,
            default_provider_id=_request_metadata_str(request, "provider_id"),
            default_model=_request_metadata_str(request, "model"),
            default_session_id=_request_session_id(request),
            default_metadata=_request_metadata(request),
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


class ApplicationPluginAgentNamespace:
    """
    application 暴露给插件的受控 Agent 命名空间。
    """

    def __init__(
        self,
        *,
        agent_orchestrator: AgentOrchestrator,
        plugin_id: str,
        default_provider_id: str | None = None,
        default_model: str | None = None,
        default_session_id: str | None = None,
        default_metadata: dict[str, object] | None = None,
    ) -> None:
        self._agent_orchestrator = agent_orchestrator
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
        max_steps: int = 4,
        required_skill_names: list[str] | None = None,
        max_skills: int | None = None,
        allowed_tool_names: list[str] | None = None,
        tool_execution_policy: ToolExecutionPolicy | None = None,
        planning: AgentPlanningConfig | None = None,
        tool_selection: AgentToolSelectionConfig | None = None,
        memory_retrieval: AgentMemoryRetrievalConfig | None = None,
        tool_choice: ToolChoice | None = None,
        max_tool_calls_per_step: int | None = None,
        max_total_tool_calls: int | None = None,
        max_tool_result_chars: int | None = None,
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
            max_steps=max_steps,
            required_skill_names=required_skill_names,
            max_skills=max_skills,
            allowed_tool_names=allowed_tool_names,
            tool_execution_policy=tool_execution_policy,
            planning=planning,
            tool_selection=tool_selection,
            memory_retrieval=memory_retrieval,
            tool_choice=tool_choice,
            max_tool_calls_per_step=max_tool_calls_per_step,
            max_total_tool_calls=max_total_tool_calls,
            max_tool_result_chars=max_tool_result_chars,
            temperature=temperature,
            max_tokens=max_tokens,
            metadata=metadata,
        )
        return _chat_response_text(result.response.message)

    async def result(
        self,
        prompt: str,
        *,
        provider_id: str | None = None,
        model: str | None = None,
        system: str | None = None,
        session_id: str | None = None,
        max_steps: int = 4,
        required_skill_names: list[str] | None = None,
        max_skills: int | None = None,
        allowed_tool_names: list[str] | None = None,
        tool_execution_policy: ToolExecutionPolicy | None = None,
        planning: AgentPlanningConfig | None = None,
        tool_selection: AgentToolSelectionConfig | None = None,
        memory_retrieval: AgentMemoryRetrievalConfig | None = None,
        tool_choice: ToolChoice | None = None,
        max_tool_calls_per_step: int | None = None,
        max_total_tool_calls: int | None = None,
        max_tool_result_chars: int | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AgentRunResult:
        resolved_provider_id = provider_id or self._default_provider_id
        resolved_model = model or self._default_model
        if not resolved_provider_id or not resolved_model:
            raise PluginConfigurationError(
                "agent.chat requires provider_id and model when no bot defaults are available"
            )

        messages: list[Message] = []
        if system:
            messages.append(_text_message(MessageRole.SYSTEM, system))
        messages.append(_text_message(MessageRole.USER, prompt))
        return await self._agent_orchestrator.run(
            build_agent_run_request(
                session_id=session_id
                or self._default_session_id
                or f"plugin:{self._plugin_id}",
                provider_id=resolved_provider_id,
                model=resolved_model,
                messages=messages,
                max_steps=max_steps,
                required_skill_names=required_skill_names or [],
                max_skills=max_skills,
                allowed_tool_names=allowed_tool_names,
                tool_execution_policy=tool_execution_policy,
                planning=planning,
                tool_selection=tool_selection,
                memory_retrieval=memory_retrieval,
                tool_choice=tool_choice,
                max_tool_calls_per_step=max_tool_calls_per_step,
                max_total_tool_calls=max_total_tool_calls,
                max_tool_result_chars=max_tool_result_chars,
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
        self._middlewares: list[PluginMiddlewareDefinition] = list(manifest.middlewares)
        self._tools: list[ToolDefinition] = list(manifest.tools)
        self._command_executors: dict[str, PluginExecutorProtocol] = {}
        self._event_executors: dict[str, PluginEventExecutorProtocol] = {}
        self._middleware_executors: dict[str, PluginMiddlewareExecutorProtocol] = {}
        self._task_executor_names: set[str] = set()
        self._event_executor_names: set[str] = set()
        self._middleware_executor_names: set[str] = set()
        self._tool_names: set[str] = set()
        self._skill_names: set[str] = set()

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    @property
    def runtime(self) -> PluginRuntimeContextProtocol:
        return self._runtime_context

    @property
    def tool_names(self) -> set[str]:
        return set(self._tool_names)

    @property
    def skill_names(self) -> set[str]:
        return set(self._skill_names)

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

    def register_middleware(
        self,
        definition: PluginMiddlewareDefinition,
        executor: PluginMiddlewareExecutorProtocol,
    ) -> None:
        self._ensure_capability(PluginCapability.MIDDLEWARE)
        self._register_middleware_definition(definition)
        middleware_name = _normalize_middleware_type(definition.middleware_type)
        if middleware_name in self._middleware_executor_names:
            raise PluginConfigurationError(f"插件中间件 {middleware_name} 重复注册")
        self._middleware_executor_names.add(middleware_name)
        self._middleware_executors[middleware_name] = executor

    def register_tool(
        self,
        definition: ToolDefinition,
        executor: ToolExecutorProtocol,
    ) -> None:
        self._runtime_context.require_permission(PluginPermission.TOOL)
        self._ensure_capability(PluginCapability.TOOL)
        if self._runtime.tool_registry is None:
            raise PluginStateError("runtime 未配置 tool registry")
        self._register_tool_definition(definition)
        self._runtime.tool_registry.register(definition, executor)
        self._tool_names.add(definition.name)

    def register_skill(self, definition: SkillDefinition) -> None:
        self._runtime_context.require_permission(PluginPermission.SKILL)
        self._ensure_capability(PluginCapability.SKILL)
        if self._skill_registry is None:
            raise PluginStateError("runtime 未配置 skill registry")
        self._skill_registry.register(definition)
        self._skill_names.add(definition.name)

    def build_definition(self) -> PluginDefinition:
        definition = self._manifest.to_definition()
        for task in self._tasks:
            if _normalize_task_name(task.name) not in self._task_executor_names:
                raise PluginConfigurationError(f"插件任务 {task.name} 未注册执行器")
        for event in self._events:
            if (
                _normalize_event_type(event.event_type)
                not in self._event_executor_names
            ):
                raise PluginConfigurationError(
                    f"插件事件 {event.event_type} 未注册执行器"
                )
        for middleware in self._middlewares:
            if (
                _normalize_middleware_type(middleware.middleware_type)
                not in self._middleware_executor_names
            ):
                raise PluginConfigurationError(
                    f"插件中间件 {middleware.middleware_type} 未注册执行器"
                )
        for tool in self._tools:
            if tool.name not in self._tool_names:
                raise PluginConfigurationError(f"插件工具 {tool.name} 未注册执行器")
        return definition.model_copy(
            update={
                "commands": list(self._commands),
                "tasks": list(self._tasks),
                "events": list(self._events),
                "middlewares": list(self._middlewares),
                "tools": list(self._tools),
            }
        )

    def build_executors(
        self,
    ) -> tuple[
        PluginExecutorProtocol | None,
        PluginEventExecutorProtocol | None,
        PluginMiddlewareExecutorProtocol | None,
    ]:
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

        middleware_executor: PluginMiddlewareExecutorProtocol | None = None
        if self._middlewares:
            middleware_executor = _PluginMiddlewareRouter(self._middleware_executors)
        return command_executor, event_executor, middleware_executor

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
        existing_names = {
            _normalize_event_type(event.event_type) for event in self._events
        }
        definition_name = _normalize_event_type(definition.event_type)
        if definition_name in existing_names:
            return
        self._events.append(definition)

    def _register_middleware_definition(
        self,
        definition: PluginMiddlewareDefinition,
    ) -> None:
        existing_names = {
            _normalize_middleware_type(middleware.middleware_type)
            for middleware in self._middlewares
        }
        definition_name = _normalize_middleware_type(definition.middleware_type)
        if definition_name in existing_names:
            return
        self._middlewares.append(definition)

    def _register_tool_definition(self, definition: ToolDefinition) -> None:
        existing_names = {tool.name for tool in self._tools}
        if definition.name in existing_names:
            return
        self._tools.append(definition)


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


class _PluginMiddlewareRouter:
    def __init__(
        self,
        executors: dict[str, PluginMiddlewareExecutorProtocol],
    ) -> None:
        self._executors = executors

    async def execute(self, request: PluginMiddlewareRequest, next_call):
        middleware_name = _normalize_middleware_type(request.route.middleware_type)
        executor = self._executors.get(middleware_name)
        if executor is None:
            raise PluginNotFoundError(f"插件中间件 {middleware_name} 不存在")
        return await executor.execute(request, next_call)


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


def _normalize_middleware_type(middleware_type: object) -> str:
    return str(middleware_type).strip().lower()


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
    return _chat_response_text(result.response.message)


def _chat_response_text(message: Message | None) -> str:
    if message is None or not message.content:
        return ""
    return "".join(
        part.text or "" for part in message.content if part.type == ContentPartType.TEXT
    )


def _request_metadata_str(
    request: (
        PluginCommandRequest
        | PluginTaskRequest
        | PluginEventRequest
        | PluginMiddlewareRequest
    ),
    key: str,
) -> str | None:
    if isinstance(request, PluginMiddlewareRequest):
        value = getattr(request.chat_request, key, None)
        if isinstance(value, str) and value:
            return value
        value = request.chat_request.metadata.get(key)
        if isinstance(value, str) and value:
            return value
        value = request.metadata.get(key)
        if isinstance(value, str) and value:
            return value
        return None
    if isinstance(request, PluginTaskRequest):
        value = request.payload.get(key)
        if isinstance(value, str) and value:
            return value
    value = request.metadata.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _request_metadata(
    request: (
        PluginCommandRequest
        | PluginTaskRequest
        | PluginEventRequest
        | PluginMiddlewareRequest
    ),
) -> dict[str, object]:
    if isinstance(request, PluginMiddlewareRequest):
        return {
            **request.chat_request.metadata,
            **request.metadata,
        }
    return dict(request.metadata)


def _request_session_id(
    request: (
        PluginCommandRequest
        | PluginTaskRequest
        | PluginEventRequest
        | PluginMiddlewareRequest
    ),
) -> str | None:
    if isinstance(request, PluginMiddlewareRequest):
        return _request_metadata_str(request, "session_id")
    if isinstance(request, PluginCommandRequest) and request.event is not None:
        return request.event.session_id
    if isinstance(request, PluginEventRequest):
        return request.event.session_id
    if isinstance(request, PluginTaskRequest):
        value = request.payload.get("session_id")
        if isinstance(value, str) and value:
            return value
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
        commands=list(manifest.commands),
    )


def _loader_status_id(loader: PluginLoaderProtocol) -> str:
    return f"loader:{loader.__class__.__module__}.{loader.__class__.__name__}"


def _module_source(
    module: PluginModuleProtocol,
    plugin_id: str,
) -> PluginSourceInfo:
    source = getattr(module, "__cyreneai_plugin_source__", None)
    if not isinstance(source, PluginSourceInfo):
        raise PluginStateError(f"插件 {plugin_id} reload 后未记录加载来源")
    return source
