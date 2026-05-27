from __future__ import annotations

from typing import Any

from cyreneAI.core.schema.tool import ToolDefinition
from cyreneAI.infra.adapters.tools.python_callable.executor import (
    PythonCallableToolExecutor,
    PythonToolCallable,
)


def define_python_tool(
    *,
    name: str,
    description: str,
    function: PythonToolCallable,
    parameters_schema: dict[str, Any] | None = None,
) -> tuple[ToolDefinition, PythonCallableToolExecutor]:
    """
    定义一个 Python callable 工具。
    """
    return (
        ToolDefinition(
            name=name,
            description=description,
            parameters_schema=parameters_schema,
        ),
        PythonCallableToolExecutor(function),
    )
