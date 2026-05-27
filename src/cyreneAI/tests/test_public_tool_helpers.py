from __future__ import annotations

import asyncio

from cyreneAI.adapters.tools import define_python_tool
from cyreneAI.core.schema.tool import ToolCall, ToolDefinition
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.registry import ToolRegistry
from cyreneAI.infra.adapters.tools.python_callable.executor import (
    PythonCallableToolExecutor,
)


def test_define_python_tool_returns_definition_and_executor() -> None:
    definition, executor = define_python_tool(
        name="lookup",
        description="Lookup a value.",
        function=lambda args: {"value": args["key"]},
        parameters_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
            },
            "required": ["key"],
        },
    )

    assert definition == ToolDefinition(
        name="lookup",
        description="Lookup a value.",
        parameters_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
            },
            "required": ["key"],
        },
    )
    assert isinstance(executor, PythonCallableToolExecutor)


def test_define_python_tool_works_with_core_tool_registry() -> None:
    async def run() -> None:
        definition, executor = define_python_tool(
            name="lookup",
            description="Lookup a value.",
            function=lambda args: {"value": args["key"]},
        )
        registry = ToolRegistry()
        registry.register(definition, executor)
        manager = ToolManager(registry)

        result = await manager.execute(
            ToolCall(
                id="call-1",
                name="lookup",
                arguments="{\"key\":\"answer\"}",
            )
        )

        assert result.content == "{\"value\": \"answer\"}"

    asyncio.run(run())
