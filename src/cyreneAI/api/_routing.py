from __future__ import annotations

from collections.abc import Callable
from inspect import signature
from typing import Any

from cyreneAI.api._arguments import (
    _command_arguments_metadata,
    _handler_description,
    _handler_type_hints,
    _normalize_command_path,
    _usage_from_arguments,
)
from cyreneAI.api._executors import (
    _CommandHandlerExecutor,
    _EventHandlerExecutor,
    _TaskHandlerExecutor,
)
from cyreneAI.api._types import (
    PluginCommandHandler,
    PluginEventHandler,
    PluginTaskHandler,
)
from cyreneAI.core.errors.plugin import PluginConfigurationError
from cyreneAI.core.plugin.plugin_protocol import PluginSetupContextProtocol
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginEventDefinition,
    PluginEventType,
    PluginManifest,
    PluginTaskDefinition,
)


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
                _CommandHandlerExecutor(
                    route.handler,
                    context.runtime,
                    route.definition,
                ),
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
        path: str | PluginCommandHandler | None = None,
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
        if callable(path):
            return self.command(
                None,
                description=description,
                usage=usage,
                aliases=aliases,
                admin_required=admin_required,
                enabled=enabled,
                metadata=metadata,
            )(path)

        command_path = path

        def decorator(handler: PluginCommandHandler) -> PluginCommandHandler:
            command_name = _join_command_paths(
                self._prefix,
                command_path or _handler_command_path(handler),
            )
            if not command_name:
                raise PluginConfigurationError("插件命令 path 必须包含命令名")

            handler_signature = signature(handler)
            type_hints = _handler_type_hints(handler)
            command_arguments = _command_arguments_metadata(
                handler_signature,
                type_hints,
            )
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
                usage=usage or _usage_from_arguments(
                    command_name,
                    command_arguments,
                ),
                arguments=command_arguments,
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
        name: str | PluginTaskHandler | None = None,
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
        if callable(name):
            return self.task(
                None,
                description=description,
                interval_seconds=interval_seconds,
                daily_at=daily_at,
                run_on_start=run_on_start,
                enabled=enabled,
                metadata=metadata,
            )(name)

        task_path = name

        def decorator(handler: PluginTaskHandler) -> PluginTaskHandler:
            task_name = _join_command_paths(
                self._prefix,
                task_path or _handler_command_path(handler),
            )
            if not task_name:
                raise PluginConfigurationError("插件任务 name 必须包含任务名")

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
        event_type: str | PluginEventType | PluginEventHandler | None = None,
        *,
        description: str | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> Callable[[PluginEventHandler], PluginEventHandler]:
        """
        注册插件事件 handler。
        """
        if callable(event_type):
            return self.event(
                None,
                description=description,
                enabled=enabled,
                metadata=metadata,
            )(event_type)

        configured_event_type = event_type

        def decorator(handler: PluginEventHandler) -> PluginEventHandler:
            normalized_event_type = _normalize_event_type(
                configured_event_type or _handler_event_type(handler)
            )
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


def _normalize_command_name(value: str) -> str:
    return _normalize_command_path(value)


def _join_command_paths(prefix: str, path: str) -> str:
    parts = [
        part
        for part in (prefix, _normalize_command_path(path))
        if part
    ]
    return " ".join(parts)


def _handler_command_path(handler: Callable[..., Any]) -> str:
    return str(getattr(handler, "__name__", "")).strip("_").replace("_", " ")


def _handler_event_type(handler: Callable[..., Any]) -> str:
    name = str(getattr(handler, "__name__", "")).strip("_").lower()
    if name.startswith("on_"):
        name = name.removeprefix("on_")
    return name


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
            "usage": _usage_from_arguments(
                name,
                list(definition.arguments),
            ),
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
