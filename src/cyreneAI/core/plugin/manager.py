from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from cyreneAI.core.errors.base import CyreneAIError
from cyreneAI.core.errors.plugin import (
    PluginAuthorizationError,
    PluginError,
    PluginExecutionError,
)
from cyreneAI.core.plugin.plugin_protocol import PluginRegistryProtocol
from cyreneAI.core.schema.chat import ChatRequest, ChatResponse
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginDefinition,
    PluginEvent,
    PluginEventDefinition,
    PluginEventRequest,
    PluginEventResult,
    PluginMiddlewareDefinition,
    PluginMiddlewareRequest,
    PluginMiddlewareType,
    PluginPermissionAuditRecord,
    PluginSourceInfo,
    PluginStatusReport,
    PluginTaskDefinition,
)

logger = logging.getLogger(__name__)


class PluginManager:
    """
    插件管理器。
    """

    def __init__(self, registry: PluginRegistryProtocol) -> None:
        self._registry = registry

    def list_plugins(self) -> list[PluginDefinition]:
        """
        列出插件。
        """
        return self._registry.list_definitions()

    def get_plugin(self, plugin_id: str) -> PluginDefinition:
        """
        获取单个插件定义。
        """
        return self._registry.get_definition(plugin_id)

    def enable_plugin(self, plugin_id: str) -> PluginDefinition:
        """
        启用插件。
        """
        return self._registry.set_enabled(plugin_id, True)

    def disable_plugin(self, plugin_id: str) -> PluginDefinition:
        """
        禁用插件。
        """
        return self._registry.set_enabled(plugin_id, False)

    def list_plugin_commands(self, plugin_id: str) -> list[PluginCommandDefinition]:
        """
        列出单个插件的已启用命令。
        """
        definition = self.get_plugin(plugin_id)
        if not definition.enabled:
            return []
        return [command for command in definition.commands if command.enabled]

    def list_plugin_events(self, plugin_id: str) -> list[PluginEventDefinition]:
        """
        列出单个插件的已启用事件订阅。
        """
        definition = self.get_plugin(plugin_id)
        if not definition.enabled:
            return []
        return [event for event in definition.events if event.enabled]

    def list_plugin_tasks(self, plugin_id: str) -> list[PluginTaskDefinition]:
        """
        列出单个插件的已启用任务。
        """
        definition = self.get_plugin(plugin_id)
        if not definition.enabled:
            return []
        return [task for task in definition.tasks if task.enabled]

    def list_plugin_middlewares(
        self,
        plugin_id: str,
    ) -> list[PluginMiddlewareDefinition]:
        """
        列出单个插件的已启用中间件。
        """
        definition = self.get_plugin(plugin_id)
        if not definition.enabled:
            return []
        return [
            middleware for middleware in definition.middlewares if middleware.enabled
        ]

    def get_plugin_status(self, plugin_id: str) -> PluginStatusReport:
        """
        获取单个插件生命周期状态。
        """
        for status in self.list_statuses():
            if status.plugin_id == plugin_id:
                return status
        raise PluginExecutionError(f"插件 {plugin_id} 状态不存在")

    def list_commands(self) -> list[PluginCommandDefinition]:
        """
        列出插件命令。
        """
        return self._registry.list_commands()

    def list_events(self) -> list[PluginEventDefinition]:
        """
        列出插件事件订阅。
        """
        return self._registry.list_events()

    def list_tasks(self) -> list[PluginTaskDefinition]:
        """
        列出插件任务。
        """
        return self._registry.list_tasks()

    def list_middlewares(self) -> list[PluginMiddlewareDefinition]:
        """
        列出插件中间件。
        """
        return self._registry.list_middlewares()

    def list_statuses(self) -> list[PluginStatusReport]:
        """
        列出插件生命周期状态。
        """
        return self._registry.list_statuses()

    def get_plugin_source(self, plugin_id: str) -> PluginSourceInfo:
        """
        获取单个插件的加载来源。
        """
        return self._registry.get_source(plugin_id)

    def list_plugin_sources(self) -> list[PluginSourceInfo]:
        """
        列出插件加载来源。
        """
        return self._registry.list_sources()

    def record_permission_audit(self, record: PluginPermissionAuditRecord) -> None:
        """
        记录插件权限检查审计。
        """
        self._registry.record_permission_audit(record)

    def list_permission_audit(
        self,
        plugin_id: str | None = None,
    ) -> list[PluginPermissionAuditRecord]:
        """
        列出插件权限检查审计。
        """
        return self._registry.list_permission_audit(plugin_id)

    async def execute_command(
        self,
        request: PluginCommandRequest,
    ) -> PluginCommandResult:
        """
        执行插件命令。
        """
        _, command, executor = self._registry.resolve_command(request.command.name)
        if command.admin_required and not request.is_admin:
            raise PluginAuthorizationError(f"插件命令 {command.name} 需要管理员权限")

        try:
            return await executor.execute(request)
        except PluginError:
            raise
        except CyreneAIError:
            raise
        except Exception as exc:
            logger.exception(
                "Plugin command failed: command=%s",
                command.name,
            )
            raise PluginExecutionError(
                f"插件命令 {command.name} 执行失败",
                cause=exc,
            ) from exc

    async def dispatch_event(
        self,
        event: PluginEvent,
        *,
        metadata: dict[str, object] | None = None,
    ) -> list[PluginEventResult]:
        """
        将窄事件分发给已订阅的插件。
        """
        results: list[PluginEventResult] = []
        for (
            plugin_definition,
            event_definition,
            executor,
        ) in self._registry.resolve_events(event):
            try:
                results.append(
                    await executor.execute(
                        PluginEventRequest(
                            route=event_definition,
                            event=event,
                            metadata=dict(metadata or {}),
                        )
                    )
                )
            except PluginError:
                raise
            except CyreneAIError:
                raise
            except Exception as exc:
                logger.exception(
                    "Plugin event failed: plugin_id=%s event_type=%s plugin_event_id=%s",
                    plugin_definition.plugin_id,
                    event_definition.event_type,
                    event.event_id,
                )
                raise PluginExecutionError(
                    f"插件事件 {event_definition.event_type} 执行失败",
                    cause=exc,
                ) from exc
        return results

    async def execute_llm_middlewares(
        self,
        chat_request: ChatRequest,
        next_call: Callable[[ChatRequest], Awaitable[ChatResponse]],
    ) -> ChatResponse:
        """
        执行 LLM 中间件链。
        """
        middlewares = self._registry.resolve_middlewares(PluginMiddlewareType.LLM)

        async def call_at(index: int, current_request: ChatRequest) -> ChatResponse:
            if index >= len(middlewares):
                return await next_call(current_request)

            plugin_definition, middleware_definition, executor = middlewares[index]

            async def call_next(
                middleware_request: PluginMiddlewareRequest,
            ) -> ChatResponse:
                return await call_at(index + 1, middleware_request.chat_request)

            try:
                return await executor.execute(
                    PluginMiddlewareRequest(
                        route=middleware_definition,
                        chat_request=current_request,
                        metadata={
                            "plugin_id": plugin_definition.plugin_id,
                        },
                    ),
                    call_next,
                )
            except PluginError:
                raise
            except CyreneAIError:
                raise
            except Exception as exc:
                logger.exception(
                    "Plugin middleware failed: plugin_id=%s middleware_type=%s",
                    plugin_definition.plugin_id,
                    middleware_definition.middleware_type,
                )
                raise PluginExecutionError(
                    f"插件中间件 {middleware_definition.middleware_type} 执行失败",
                    cause=exc,
                ) from exc

        return await call_at(0, chat_request)
