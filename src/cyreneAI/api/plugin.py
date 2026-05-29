from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from inspect import Parameter, Signature, isasyncgen, isawaitable, isgenerator, signature
from typing import Any, Literal, TypeAlias, overload

from cyreneAI.core.errors.plugin import (
    PluginConfigurationError,
    PluginError,
    PluginExecutionError,
    PluginInputError,
)
from cyreneAI.core.plugin.plugin_protocol import (
    PluginAssetsNamespaceProtocol,
    PluginLLMNamespaceProtocol,
    PluginOutboxNamespaceProtocol,
    PluginRuntimeContextProtocol,
    PluginSetupContextProtocol,
    PluginStorageNamespaceProtocol,
    PluginTaskNamespaceProtocol,
)
from cyreneAI.core.schema.application import (
    ApplicationImageGenerationRequest,
    ApplicationImageGenerationResult,
)
from cyreneAI.core.schema.bot import BotAction, BotActionType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.provider import ProviderInfo, ProviderModel
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginEventDefinition,
    PluginEventRequest,
    PluginEventResult,
    PluginEventType,
    PluginManifest,
    PluginPermission,
    PluginTaskDefinition,
    PluginTaskRequest,
    PluginTaskResult,
)


PluginCommandHandlerResult: TypeAlias = str | PluginCommandResult
PluginCommandGenerator: TypeAlias = Generator[
    PluginCommandHandlerResult,
    None,
    Any,
]
PluginCommandAsyncGenerator: TypeAlias = AsyncGenerator[
    PluginCommandHandlerResult,
    None,
]
PluginCommandHandlerReturn: TypeAlias = (
    PluginCommandHandlerResult
    | PluginCommandGenerator
    | PluginCommandAsyncGenerator
    | Awaitable[PluginCommandHandlerResult]
)
PluginCommandHandler: TypeAlias = Callable[..., PluginCommandHandlerReturn]
PluginTaskHandler = Callable[
    ...,
    PluginTaskResult | None | Awaitable[PluginTaskResult | None],
]
PluginEventHandler = Callable[
    ...,
    PluginEventResult | None | Awaitable[PluginEventResult | None],
]


class PluginDependency:
    """
    插件 handler 依赖声明。
    """

    def __init__(self, name: str) -> None:
        normalized_name = name.strip().lower()
        if not normalized_name:
            raise PluginConfigurationError("插件依赖名称不能为空")
        self.name = normalized_name


@overload
def Depends(
    name: Literal["ctx", "context", "runtime"],
) -> PluginRuntimeContextProtocol: ...


@overload
def Depends(name: Literal["llm"]) -> PluginLLMNamespaceProtocol: ...


@overload
def Depends(
    name: Literal["image", "generate_image"],
) -> Callable[
    [ApplicationImageGenerationRequest],
    Awaitable[ApplicationImageGenerationResult],
]: ...


@overload
def Depends(
    name: Literal["providers", "list_providers"],
) -> Callable[[], list[ProviderInfo]]: ...


@overload
def Depends(
    name: Literal["provider_models", "list_provider_models"],
) -> Callable[[str], Awaitable[list[ProviderModel]]]: ...


@overload
def Depends(name: Literal["storage"]) -> PluginStorageNamespaceProtocol: ...


@overload
def Depends(name: Literal["assets"]) -> PluginAssetsNamespaceProtocol: ...


@overload
def Depends(
    name: Literal["task", "tasks", "scheduler"],
) -> PluginTaskNamespaceProtocol: ...


@overload
def Depends(
    name: Literal["message", "messages", "outbox"],
) -> PluginOutboxNamespaceProtocol: ...


@overload
def Depends(name: str) -> Any: ...


def Depends(name: str) -> Any:
    """
    声明插件 handler 需要宿主注入的受控能力。
    """
    return PluginDependency(name)


class CyreneBot:
    """
    第三方 bot 插件根 router。
    """

    def __init__(self, manifest: PluginManifest | None = None) -> None:
        self._manifest = manifest
        self._router = CyreneRouter()

    @property
    def manifest(self) -> PluginManifest:
        if self._manifest is None:
            raise PluginConfigurationError("插件缺少 plugin.json manifest")
        return self._manifest

    @property
    def routes(self) -> tuple[PluginCommandDefinition, ...]:
        return self._router.routes

    @property
    def tasks(self) -> tuple[PluginTaskDefinition, ...]:
        return self._router.tasks

    @property
    def events(self) -> tuple[PluginEventDefinition, ...]:
        return self._router.events

    def configure(self, manifest: PluginManifest) -> "CyreneBot":
        """
        注入 plugin.json 清单。
        """
        self._manifest = manifest
        return self

    def command(self, *args: Any, **kwargs: Any):
        """
        注册 bot 命令 handler。
        """
        return self._router.command(*args, **kwargs)

    def task(self, *args: Any, **kwargs: Any):
        """
        注册受管后台任务 handler。
        """
        return self._router.task(*args, **kwargs)

    def event(self, *args: Any, **kwargs: Any):
        """
        注册插件事件 handler。
        """
        return self._router.event(*args, **kwargs)

    def include_router(self, router: "CyreneRouter") -> None:
        """
        挂载子 router。
        """
        self._router.include_router(router)

    def setup(self, context: PluginSetupContextProtocol) -> None:
        """
        将当前 router 中的命令注册到插件宿主。
        """
        for route in self._router.command_routes:
            context.register_command(
                route.definition,
                _CommandHandlerExecutor(route.handler, context.runtime),
            )
        for route in self._router.task_routes:
            context.register_task(
                route.definition,
                _TaskHandlerExecutor(route.handler, context.runtime),
            )
        for route in self._router.event_routes:
            context.register_event(
                route.definition,
                _EventHandlerExecutor(route.handler, context.runtime),
            )


class CyreneRouter:
    """
    第三方 bot 插件 router。
    """

    def __init__(
        self,
        *,
        prefix: str = "",
        admin_required: bool = False,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._prefix = _normalize_command_path(prefix)
        self._admin_required = admin_required
        self._enabled = enabled
        self._metadata = metadata or {}
        self._routes: list[_CommandRoute] = []
        self._tasks: list[_TaskRoute] = []
        self._events: list[_EventRoute] = []

    @property
    def routes(self) -> tuple[PluginCommandDefinition, ...]:
        return tuple(route.definition for route in self._routes)

    @property
    def command_routes(self) -> tuple["_CommandRoute", ...]:
        return tuple(self._routes)

    @property
    def tasks(self) -> tuple[PluginTaskDefinition, ...]:
        return tuple(route.definition for route in self._tasks)

    @property
    def task_routes(self) -> tuple["_TaskRoute", ...]:
        return tuple(self._tasks)

    @property
    def events(self) -> tuple[PluginEventDefinition, ...]:
        return tuple(route.definition for route in self._events)

    @property
    def event_routes(self) -> tuple["_EventRoute", ...]:
        return tuple(self._events)

    def command(
        self,
        path: str,
        *,
        description: str | None = None,
        usage: str | None = None,
        aliases: list[str] | None = None,
        admin_required: bool = False,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> Callable[[PluginCommandHandler], PluginCommandHandler]:
        """
        注册 bot 命令 handler。
        """
        command_name = _join_command_paths(self._prefix, path)
        if not command_name:
            raise PluginConfigurationError("插件命令 path 必须包含命令名")

        def decorator(handler: PluginCommandHandler) -> PluginCommandHandler:
            command_description = description
            if command_description is None:
                command_description = _handler_description(handler)

            route_metadata = {
                **self._metadata,
                **(metadata or {}),
            }
            definition = PluginCommandDefinition(
                name=command_name,
                description=command_description,
                usage=usage or _default_usage(command_name),
                aliases=[
                    normalized_alias
                    for alias in aliases or []
                    if (
                        normalized_alias := _join_command_paths(
                            self._prefix,
                            alias,
                        )
                    )
                ],
                admin_required=self._admin_required or admin_required,
                enabled=self._enabled and enabled,
                metadata=route_metadata,
            )
            self._routes.append(_CommandRoute(definition, handler))
            return handler

        return decorator

    def task(
        self,
        name: str,
        *,
        description: str | None = None,
        interval_seconds: float | None = None,
        daily_at: str | None = None,
        run_on_start: bool = False,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> Callable[[PluginTaskHandler], PluginTaskHandler]:
        """
        注册受管后台任务 handler。
        """
        task_name = _join_command_paths(self._prefix, name)
        if not task_name:
            raise PluginConfigurationError("插件任务 name 必须包含任务名")

        def decorator(handler: PluginTaskHandler) -> PluginTaskHandler:
            task_description = description
            if task_description is None:
                task_description = _handler_description(handler)

            task_metadata = {
                **self._metadata,
                **(metadata or {}),
            }
            definition = PluginTaskDefinition(
                name=task_name,
                description=task_description,
                interval_seconds=interval_seconds,
                daily_at=daily_at,
                run_on_start=run_on_start,
                enabled=self._enabled and enabled,
                metadata=task_metadata,
            )
            self._tasks.append(_TaskRoute(definition, handler))
            return handler

        return decorator

    def event(
        self,
        event_type: str | PluginEventType,
        *,
        description: str | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> Callable[[PluginEventHandler], PluginEventHandler]:
        """
        注册插件事件 handler。
        """
        normalized_event_type = _normalize_event_type(event_type)

        def decorator(handler: PluginEventHandler) -> PluginEventHandler:
            event_description = description
            if event_description is None:
                event_description = _handler_description(handler)

            event_metadata = {
                **self._metadata,
                **(metadata or {}),
            }
            definition = PluginEventDefinition(
                event_type=normalized_event_type,
                description=event_description,
                enabled=self._enabled and enabled,
                metadata=event_metadata,
            )
            self._events.append(_EventRoute(definition, handler))
            return handler

        return decorator

    def include_router(self, router: "CyreneRouter") -> None:
        """
        挂载子 router。
        """
        for route in router.command_routes:
            self._routes.append(
                _CommandRoute(
                    _merge_router_definition(
                        route.definition,
                        prefix=self._prefix,
                        admin_required=self._admin_required,
                        enabled=self._enabled,
                        metadata=self._metadata,
                    ),
                    route.handler,
                )
            )
        for route in router.task_routes:
            self._tasks.append(
                _TaskRoute(
                    _merge_router_task_definition(
                        route.definition,
                        prefix=self._prefix,
                        enabled=self._enabled,
                        metadata=self._metadata,
                    ),
                    route.handler,
                )
            )
        for route in router.event_routes:
            self._events.append(
                _EventRoute(
                    _merge_router_event_definition(
                        route.definition,
                        enabled=self._enabled,
                        metadata=self._metadata,
                    ),
                    route.handler,
                )
            )


class _CommandRoute:
    def __init__(
        self,
        definition: PluginCommandDefinition,
        handler: PluginCommandHandler,
    ) -> None:
        self.definition = definition
        self.handler = handler


class _TaskRoute:
    def __init__(
        self,
        definition: PluginTaskDefinition,
        handler: PluginTaskHandler,
    ) -> None:
        self.definition = definition
        self.handler = handler


class _EventRoute:
    def __init__(
        self,
        definition: PluginEventDefinition,
        handler: PluginEventHandler,
    ) -> None:
        self.definition = definition
        self.handler = handler


class _CommandHandlerExecutor:
    def __init__(
        self,
        handler: PluginCommandHandler,
        runtime_context: Any,
    ) -> None:
        self._handler = handler
        self._runtime_context = runtime_context
        self._signature = signature(handler)
        _validate_handler_signature(self._signature, runtime_context)

    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        try:
            args, kwargs = _build_handler_arguments(
                self._signature,
                request,
                self._runtime_context,
            )
            result = self._handler(*args, **kwargs)
            if isawaitable(result):
                result = await result
        except PluginError:
            raise
        except Exception as exc:
            raise PluginExecutionError(
                f"插件命令 {request.command.name} 执行失败",
                cause=exc,
            ) from exc

        return await _coerce_command_handler_result(request, result)


class _TaskHandlerExecutor:
    def __init__(
        self,
        handler: PluginTaskHandler,
        runtime_context: Any,
    ) -> None:
        self._handler = handler
        self._runtime_context = runtime_context
        self._signature = signature(handler)
        _validate_handler_signature(self._signature, runtime_context, "插件任务")

    async def execute(self, request: PluginTaskRequest) -> PluginTaskResult:
        try:
            args, kwargs = _build_handler_arguments(
                self._signature,
                request,
                self._runtime_context,
            )
            result = self._handler(*args, **kwargs)
            if isawaitable(result):
                result = await result
        except PluginError:
            raise
        except Exception as exc:
            raise PluginExecutionError(
                f"插件任务 {request.task.name} 执行失败",
                cause=exc,
            ) from exc

        if result is None:
            return PluginTaskResult()
        if not isinstance(result, PluginTaskResult):
            raise PluginExecutionError(
                f"插件任务 {request.task.name} 必须返回 PluginTaskResult 或 None"
            )
        return result


class _EventHandlerExecutor:
    def __init__(
        self,
        handler: PluginEventHandler,
        runtime_context: Any,
    ) -> None:
        self._handler = handler
        self._runtime_context = runtime_context
        self._signature = signature(handler)
        _validate_handler_signature(self._signature, runtime_context, "插件事件")

    async def execute(self, request: PluginEventRequest) -> PluginEventResult:
        try:
            args, kwargs = _build_handler_arguments(
                self._signature,
                request,
                self._runtime_context,
            )
            result = self._handler(*args, **kwargs)
            if isawaitable(result):
                result = await result
        except PluginError:
            raise
        except Exception as exc:
            raise PluginExecutionError(
                f"插件事件 {request.route.event_type} 执行失败",
                cause=exc,
            ) from exc

        if result is None:
            return PluginEventResult()
        if not isinstance(result, PluginEventResult):
            raise PluginExecutionError(
                f"插件事件 {request.route.event_type} 必须返回 PluginEventResult 或 None"
            )
        return result


def text(
    request: PluginCommandRequest,
    content: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> PluginCommandResult:
    """
    构造文本回复结果。
    """
    if request.event is None:
        raise PluginInputError("text reply requires request.event")

    action = BotAction(
        action_type=BotActionType.SEND_MESSAGE,
        channel_id=request.event.channel_id,
        session_id=request.event.session_id,
        recipient_id=request.event.user_id,
        thread_id=request.event.thread_id,
        message=BotMessage(
            sender_id="bot",
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=content,
                )
            ],
            metadata={
                "command": request.command.name,
                **(metadata or {}),
            },
        ),
        metadata={
            "bot_event_id": request.event.event_id,
            "command": request.command.name,
            **(metadata or {}),
        },
    )
    return PluginCommandResult(
        actions=[action],
        metadata=metadata or {},
    )


async def _coerce_command_handler_result(
    request: PluginCommandRequest,
    result: Any,
) -> PluginCommandResult:
    if isinstance(result, str):
        return text(request, result)
    if isinstance(result, PluginCommandResult):
        return result
    if isasyncgen(result):
        partials: list[PluginCommandResult] = []
        async for item in result:
            partials.append(_coerce_command_result_item(request, item))
        return _merge_command_results(partials)
    if isgenerator(result):
        return _merge_command_results(
            [
                _coerce_command_result_item(request, item)
                for item in result
            ]
        )
    raise PluginExecutionError(
        f"插件命令 {request.command.name} 必须返回 str、PluginCommandResult，或 yield 它们"
    )


def _coerce_command_result_item(
    request: PluginCommandRequest,
    item: Any,
) -> PluginCommandResult:
    if isinstance(item, str):
        return text(request, item)
    if isinstance(item, PluginCommandResult):
        return item
    raise PluginExecutionError(
        f"插件命令 {request.command.name} yield 项必须是 str 或 PluginCommandResult"
    )


def _merge_command_results(
    results: list[PluginCommandResult],
) -> PluginCommandResult:
    actions: list[BotAction] = []
    metadata: dict[str, Any] = {}
    handled = True
    for result in results:
        handled = handled and result.handled
        actions.extend(result.actions)
        metadata.update(result.metadata)
    return PluginCommandResult(
        handled=handled,
        actions=actions,
        metadata=metadata,
    )


def _normalize_command_name(value: str) -> str:
    return _normalize_command_path(value)


def _normalize_command_path(value: str) -> str:
    stripped = value.strip().removeprefix("/")
    if not stripped:
        return ""
    return " ".join(stripped.replace("/", " ").split()).lower()


def _join_command_paths(prefix: str, path: str) -> str:
    parts = [
        part
        for part in (prefix, _normalize_command_path(path))
        if part
    ]
    return " ".join(parts)


def _default_usage(path: str) -> str:
    normalized = _normalize_command_path(path)
    if not normalized:
        return ""
    return f"/{normalized}"


def _normalize_event_type(value: str | PluginEventType) -> PluginEventType:
    try:
        return PluginEventType(str(value).strip().lower())
    except ValueError as exc:
        raise PluginConfigurationError(f"未知插件事件类型: {value}") from exc


def _merge_router_definition(
    definition: PluginCommandDefinition,
    *,
    prefix: str,
    admin_required: bool,
    enabled: bool,
    metadata: dict[str, Any],
) -> PluginCommandDefinition:
    if not prefix:
        return definition.model_copy(
            update={
                "admin_required": admin_required or definition.admin_required,
                "enabled": enabled and definition.enabled,
                "metadata": {**metadata, **definition.metadata},
            }
        )

    name = _join_command_paths(prefix, definition.name)
    aliases = [_join_command_paths(prefix, alias) for alias in definition.aliases]
    return definition.model_copy(
        update={
            "name": name,
            "usage": _default_usage(name),
            "aliases": [alias for alias in aliases if alias],
            "admin_required": admin_required or definition.admin_required,
            "enabled": enabled and definition.enabled,
            "metadata": {**metadata, **definition.metadata},
        }
    )


def _merge_router_task_definition(
    definition: PluginTaskDefinition,
    *,
    prefix: str,
    enabled: bool,
    metadata: dict[str, Any],
) -> PluginTaskDefinition:
    if not prefix:
        return definition.model_copy(
            update={
                "enabled": enabled and definition.enabled,
                "metadata": {**metadata, **definition.metadata},
            }
        )

    return definition.model_copy(
        update={
            "name": _join_command_paths(prefix, definition.name),
            "enabled": enabled and definition.enabled,
            "metadata": {**metadata, **definition.metadata},
        }
    )


def _merge_router_event_definition(
    definition: PluginEventDefinition,
    *,
    enabled: bool,
    metadata: dict[str, Any],
) -> PluginEventDefinition:
    return definition.model_copy(
        update={
            "enabled": enabled and definition.enabled,
            "metadata": {**metadata, **definition.metadata},
        }
    )


def _handler_description(handler: PluginCommandHandler) -> str:
    doc = getattr(handler, "__doc__", None)
    if not doc:
        return ""
    return doc.strip().splitlines()[0].strip()


def _build_handler_arguments(
    handler_signature: Signature,
    request: PluginCommandRequest | PluginTaskRequest | PluginEventRequest,
    runtime_context: Any,
) -> tuple[list[Any], dict[str, Any]]:
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    slot_index = 0

    for parameter in handler_signature.parameters.values():
        if parameter.kind in {
            Parameter.VAR_POSITIONAL,
            Parameter.VAR_KEYWORD,
        }:
            raise PluginConfigurationError("插件命令 handler 不支持 *args 或 **kwargs")

        value = _resolve_handler_parameter(
            parameter,
            request,
            runtime_context,
            slot_index,
        )
        if value is _UNSET:
            continue

        if parameter.default is _empty:
            slot_index = _advance_slot_index(
                slot_index,
                value,
                request,
                runtime_context,
            )

        if parameter.kind is Parameter.POSITIONAL_ONLY:
            args.append(value)
        else:
            kwargs[parameter.name] = value

    return args, kwargs


def _validate_handler_signature(
    handler_signature: Signature,
    runtime_context: Any,
    handler_label: str = "插件命令",
) -> None:
    slot_index = 0
    for parameter in handler_signature.parameters.values():
        if parameter.kind in {
            Parameter.VAR_POSITIONAL,
            Parameter.VAR_KEYWORD,
        }:
            raise PluginConfigurationError(
                f"{handler_label} handler 不支持 *args 或 **kwargs"
            )
        if isinstance(parameter.default, PluginDependency):
            _resolve_dependency(parameter.default, runtime_context)
            continue
        if parameter.default is not _empty:
            continue
        if parameter.name == "request":
            slot_index = max(slot_index, 1)
            continue
        if parameter.name in {"ctx", "context"}:
            slot_index = max(slot_index, 2)
            continue
        if slot_index < 2:
            slot_index += 1
            continue
        raise PluginConfigurationError(
            f"{handler_label} handler 参数 {parameter.name} 无法注入"
        )


def _resolve_handler_parameter(
    parameter: Parameter,
    request: PluginCommandRequest | PluginTaskRequest | PluginEventRequest,
    runtime_context: Any,
    slot_index: int,
) -> Any:
    if isinstance(parameter.default, PluginDependency):
        return _resolve_dependency(parameter.default, runtime_context, request)

    if parameter.name == "request":
        return request
    if parameter.name == "event" and isinstance(request, PluginEventRequest):
        return request.event
    if parameter.name in {"ctx", "context"}:
        return runtime_context
    if parameter.default is not _empty:
        return _UNSET

    positional_slots = (request, runtime_context)
    if slot_index >= len(positional_slots):
        raise PluginConfigurationError(
            f"插件命令 handler 参数 {parameter.name} 无法注入"
        )
    return positional_slots[slot_index]


def _resolve_dependency(
    dependency: PluginDependency,
    runtime_context: Any,
    request: PluginCommandRequest | PluginTaskRequest | PluginEventRequest | None = None,
) -> Any:
    if dependency.name in {"ctx", "context", "runtime"}:
        return runtime_context
    if dependency.name == "llm":
        runtime_context.require_permission(PluginPermission.LLM)
        llm_for_request = getattr(runtime_context, "llm_for_request", None)
        if llm_for_request is not None and request is not None:
            return llm_for_request(request)
        return runtime_context.llm
    if dependency.name in {"image", "generate_image"}:
        runtime_context.require_permission(PluginPermission.IMAGE)
        return runtime_context.generate_image
    if dependency.name in {"providers", "list_providers"}:
        runtime_context.require_permission(PluginPermission.PROVIDER_READ)
        return runtime_context.list_providers
    if dependency.name in {"provider_models", "list_provider_models"}:
        runtime_context.require_permission(PluginPermission.PROVIDER_READ)
        return runtime_context.list_provider_models
    if dependency.name == "storage":
        return runtime_context.storage
    if dependency.name == "assets":
        return runtime_context.assets
    if dependency.name in {"task", "tasks", "scheduler"}:
        return runtime_context.tasks
    if dependency.name in {"message", "messages", "outbox"}:
        return runtime_context.messages
    raise PluginConfigurationError(f"未知插件依赖: {dependency.name}")


def _advance_slot_index(
    slot_index: int,
    value: Any,
    request: PluginCommandRequest | PluginTaskRequest | PluginEventRequest,
    runtime_context: Any,
) -> int:
    if value is request:
        return max(slot_index, 1)
    if value is runtime_context:
        return max(slot_index, 2)
    return slot_index + 1


class _Unset:
    pass


_UNSET = _Unset()
_empty = Signature.empty
