from __future__ import annotations

from inspect import isawaitable, signature
from typing import Any

from cyreneAI.api._arguments import (
    _build_handler_arguments,
    _handler_type_hints,
    _validate_handler_signature,
)
from cyreneAI.api._replies import _coerce_command_handler_result
from cyreneAI.api._types import (
    PluginCommandHandler,
    PluginEventHandler,
    PluginTaskHandler,
)
from cyreneAI.core.errors.plugin import PluginError, PluginExecutionError
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginEventRequest,
    PluginEventResult,
    PluginTaskRequest,
    PluginTaskResult,
)


class _CommandHandlerExecutor:
    def __init__(
        self,
        handler: PluginCommandHandler,
        runtime_context: Any,
        definition: PluginCommandDefinition,
    ) -> None:
        self._handler = handler
        self._runtime_context = runtime_context
        self._definition = definition
        self._signature = signature(handler)
        self._type_hints = _handler_type_hints(handler)
        _validate_handler_signature(
            self._signature,
            runtime_context,
            type_hints=self._type_hints,
        )

    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        try:
            args, kwargs = _build_handler_arguments(
                self._signature,
                request,
                self._runtime_context,
                usage=self._definition.usage,
                type_hints=self._type_hints,
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
        self._type_hints = _handler_type_hints(handler)
        _validate_handler_signature(
            self._signature,
            runtime_context,
            "插件任务",
            type_hints=self._type_hints,
        )

    async def execute(self, request: PluginTaskRequest) -> PluginTaskResult:
        try:
            args, kwargs = _build_handler_arguments(
                self._signature,
                request,
                self._runtime_context,
                type_hints=self._type_hints,
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
        self._type_hints = _handler_type_hints(handler)
        _validate_handler_signature(
            self._signature,
            runtime_context,
            "插件事件",
            type_hints=self._type_hints,
        )

    async def execute(self, request: PluginEventRequest) -> PluginEventResult:
        try:
            args, kwargs = _build_handler_arguments(
                self._signature,
                request,
                self._runtime_context,
                type_hints=self._type_hints,
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
