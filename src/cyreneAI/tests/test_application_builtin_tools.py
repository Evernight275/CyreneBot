from __future__ import annotations

import asyncio
import json

import pytest

from cyreneAI.bootstrap import build_cyrene_ai_runtime
from cyreneAI.core.errors.tool import ToolExecutionError
from cyreneAI.core.schema.tool import ToolCall


async def _run_builtin_tools_are_registered_by_default() -> None:
    runtime = await build_cyrene_ai_runtime(register_builtin_plugins=False)
    try:
        assert runtime.tool_registry is not None
        tool_names = {
            definition.name for definition in runtime.tool_registry.list_definitions()
        }
        assert {
            "get_current_time",
            "calculate",
            "json_get",
            "text_search",
        }.issubset(tool_names)
    finally:
        await runtime.close()


def test_builtin_tools_are_registered_by_default() -> None:
    asyncio.run(_run_builtin_tools_are_registered_by_default())


async def _run_builtin_tools_can_be_disabled() -> None:
    runtime = await build_cyrene_ai_runtime(
        register_builtin_plugins=False,
        register_builtin_tools=False,
    )
    try:
        assert runtime.tool_registry is not None
        assert runtime.tool_registry.list_definitions() == []
    finally:
        await runtime.close()


def test_builtin_tools_can_be_disabled() -> None:
    asyncio.run(_run_builtin_tools_can_be_disabled())


async def _run_core_builtin_tools_execute() -> None:
    runtime = await build_cyrene_ai_runtime(register_builtin_plugins=False)
    try:
        assert runtime.tool_manager is not None

        time_result = await runtime.tool_manager.execute(
            ToolCall(
                id="call-time",
                name="get_current_time",
                arguments=json.dumps({"utc_offset": "+08:00"}),
            )
        )
        time_payload = json.loads(time_result.content or "{}")
        assert time_payload["utc_offset"] == "+08:00"
        assert "iso" in time_payload

        calculate_result = await runtime.tool_manager.execute(
            ToolCall(
                id="call-calculate",
                name="calculate",
                arguments=json.dumps({"expression": "sqrt(81) + 3 * 2"}),
            )
        )
        calculate_payload = json.loads(calculate_result.content or "{}")
        assert calculate_payload == {
            "expression": "sqrt(81) + 3 * 2",
            "result": 15,
        }

        json_result = await runtime.tool_manager.execute(
            ToolCall(
                id="call-json",
                name="json_get",
                arguments=json.dumps(
                    {
                        "json": json.dumps(
                            {
                                "users": [
                                    {
                                        "name": "Cyrene",
                                        "roles": ["agent", "director"],
                                    }
                                ]
                            }
                        ),
                        "path": "users.0.roles.1",
                    }
                ),
            )
        )
        json_payload = json.loads(json_result.content or "{}")
        assert json_payload == {
            "path": "users.0.roles.1",
            "value": "director",
        }

        search_result = await runtime.tool_manager.execute(
            ToolCall(
                id="call-search",
                name="text_search",
                arguments=json.dumps(
                    {
                        "text": "Agent tools make agent loops useful. Tools matter.",
                        "query": "tools",
                        "max_matches": 2,
                    }
                ),
            )
        )
        search_payload = json.loads(search_result.content or "{}")
        assert search_payload["match_count"] == 2
        assert search_payload["matches"][0]["match"] == "tools"
    finally:
        await runtime.close()


def test_core_builtin_tools_execute() -> None:
    asyncio.run(_run_core_builtin_tools_execute())


async def _run_calculate_rejects_unsafe_expression() -> None:
    runtime = await build_cyrene_ai_runtime(register_builtin_plugins=False)
    try:
        assert runtime.tool_manager is not None
        with pytest.raises(ToolExecutionError):
            await runtime.tool_manager.execute(
                ToolCall(
                    id="call-unsafe",
                    name="calculate",
                    arguments=json.dumps(
                        {"expression": "__import__('os').system('echo nope')"}
                    ),
                )
            )
    finally:
        await runtime.close()


def test_calculate_rejects_unsafe_expression() -> None:
    asyncio.run(_run_calculate_rejects_unsafe_expression())
