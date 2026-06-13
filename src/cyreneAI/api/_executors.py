from __future__ import annotations

import json
from inspect import Signature, isawaitable, signature
from typing import Any, cast

from cyreneAI.api._arguments import (
    _build_handler_arguments,
    _handler_type_hints,
    _validate_handler_signature,
)
from cyreneAI.api._replies import _coerce_command_handler_result
from cyreneAI.api._types import (
    PluginCommandHandler,
    PluginEventHandler,
    PluginMiddlewareHandler,
    PluginTaskHandler,
    PluginToolHandler,
)
from cyreneAI.core.errors.plugin import PluginError, PluginExecutionError
from cyreneAI.core.errors.tool import ToolError, ToolExecutionError, ToolInputError
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginEventRequest,
    PluginEventResult,
    PluginMiddlewareRequest,
    PluginTaskRequest,
    PluginTaskResult,
)
from cyreneAI.core.schema.tool import ToolCall, ToolResult


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


class _MiddlewareHandlerExecutor:
    def __init__(
        self,
        handler: PluginMiddlewareHandler,
        runtime_context: Any,
    ) -> None:
        self._handler = handler
        self._runtime_context = runtime_context
        self._signature = signature(handler)
        self._type_hints = _handler_type_hints(handler)
        _validate_handler_signature(
            self._signature,
            runtime_context,
            "插件中间件",
            type_hints=self._type_hints,
        )

    async def execute(self, request: PluginMiddlewareRequest, next_call):
        try:
            args, kwargs = _build_handler_arguments(
                self._signature,
                request,
                self._runtime_context,
                type_hints=self._type_hints,
            )
            for name in ("next", "call_next"):
                if name in self._signature.parameters and name not in kwargs:
                    kwargs[name] = next_call
            result = self._handler(*args, **kwargs)
            if isawaitable(result):
                result = await result
        except PluginError:
            raise
        except Exception as exc:
            raise PluginExecutionError(
                f"插件中间件 {request.route.middleware_type} 执行失败",
                cause=exc,
            ) from exc
        return result


class _ToolHandlerExecutor:
    def __init__(
        self,
        handler: PluginToolHandler,
        runtime_context: Any,
    ) -> None:
        self._handler = handler
        self._runtime_context = runtime_context
        self._signature = signature(handler)
        self._type_hints = _handler_type_hints(handler)

    async def execute(self, call: ToolCall) -> ToolResult:
        try:
            arguments = _parse_tool_arguments(call.arguments)
            args, kwargs = _build_tool_handler_arguments(
                self._signature,
                self._type_hints,
                arguments,
                call,
                self._runtime_context,
            )
            result = self._handler(*args, **kwargs)
            if isawaitable(result):
                result = await result
        except (PluginError, ToolError):
            raise
        except Exception as exc:
            raise ToolExecutionError(
                f"插件工具 {call.name} 执行失败",
                cause=exc,
            ) from exc

        return _coerce_tool_handler_result(call, result)


def _parse_tool_arguments(arguments: str | None) -> dict[str, Any]:
    if not arguments:
        return {}
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise ToolInputError("Tool arguments must be valid JSON", cause=exc) from exc
    if not isinstance(parsed, dict):
        raise ToolInputError("Tool arguments must be a JSON object")
    return cast(dict[str, Any], parsed)


def _build_tool_handler_arguments(
    handler_signature: Signature,
    type_hints: dict[str, Any],
    arguments: dict[str, Any],
    call: ToolCall,
    runtime_context: Any,
) -> tuple[list[Any], dict[str, Any]]:
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    for name, parameter in handler_signature.parameters.items():
        annotation = type_hints.get(name, parameter.annotation)
        value_set = False
        value: Any = None
        if name in {"call", "tool_call"} or annotation is ToolCall:
            value = call
            value_set = True
        elif name in {"ctx", "context", "runtime"}:
            value = runtime_context
            value_set = True
        elif name in arguments:
            value = _coerce_tool_argument(arguments[name], annotation)
            value_set = True

        if not value_set:
            if parameter.default is not parameter.empty:
                continue
            raise ToolInputError(f"{name} is required")

        if parameter.kind in (
            parameter.POSITIONAL_ONLY,
            parameter.POSITIONAL_OR_KEYWORD,
        ):
            args.append(value)
        elif parameter.kind == parameter.KEYWORD_ONLY:
            kwargs[name] = value
        else:
            raise ToolInputError(f"Unsupported tool handler parameter: {name}")
    return args, kwargs


def _coerce_tool_argument(value: Any, annotation: Any) -> Any:
    if annotation in {str, int, float, bool}:
        if annotation is bool and not isinstance(value, bool):
            raise ToolInputError("value must be a boolean")
        if annotation is int and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            raise ToolInputError("value must be an integer")
        if annotation is float and (
            not isinstance(value, (int, float)) or isinstance(value, bool)
        ):
            raise ToolInputError("value must be a number")
        if annotation is str and not isinstance(value, str):
            raise ToolInputError("value must be a string")
    return value


def _coerce_tool_handler_result(call: ToolCall, result: Any) -> ToolResult:
    if isinstance(result, ToolResult):
        return result.model_copy(update={"call_id": call.id, "name": call.name})
    if isinstance(result, dict):
        content = json.dumps(result, ensure_ascii=False, sort_keys=True)
    elif result is None:
        content = ""
    else:
        content = str(result)
    return ToolResult(call_id=call.id, name=call.name, content=content)
