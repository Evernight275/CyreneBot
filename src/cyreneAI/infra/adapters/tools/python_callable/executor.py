from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from cyreneAI.core.errors.tool import ToolExecutionError
from cyreneAI.core.schema.tool import ToolCall, ToolResult
from cyreneAI.infra.adapters.tools.common import (
    ToolResultPayload,
    map_tool_result,
    parse_tool_arguments,
)

PythonToolCallable = Callable[
    [dict[str, Any]],
    ToolResultPayload | Awaitable[ToolResultPayload],
]


class PythonCallableToolExecutor:
    """
    Python callable 工具执行器
    """

    def __init__(self, function: PythonToolCallable) -> None:
        self._function = function

    async def execute(self, call: ToolCall) -> ToolResult:
        """
        执行 Python callable 工具
        """
        arguments = parse_tool_arguments(call.arguments)
        try:
            result = self._function(arguments)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise ToolExecutionError(
                f"Tool {call.name} execution failed",
                cause=exc,
            ) from exc

        return map_tool_result(call, result)
