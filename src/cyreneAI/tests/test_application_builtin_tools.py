from __future__ import annotations

import asyncio
import json

import pytest

from cyreneAI.bootstrap import build_cyrene_ai_runtime
from cyreneAI.application.tools import builtin
from cyreneAI.application.tools.builtin import register_core_builtin_tools
from cyreneAI.application.tools import todo
from cyreneAI.application.tools.todo import register_todo_tools
from cyreneAI.core.errors.tool import ToolExecutionError, ToolInputError
from cyreneAI.core.schema.tool import ToolCall
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.registry import ToolRegistry


def _tool_call(name: str, arguments: object, *, call_id: str = "call") -> ToolCall:
    return ToolCall(
        id=call_id,
        name=name,
        arguments=arguments if isinstance(arguments, str) else json.dumps(arguments),
    )


def _builtin_tool_manager() -> ToolManager:
    registry = ToolRegistry()
    register_core_builtin_tools(registry)
    register_todo_tools(registry)
    return ToolManager(registry)


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
            "create_todo",
            "list_todos",
            "complete_todo",
        }.issubset(tool_names)
        assert "code_interpreter" not in tool_names
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

        create_todo_result = await runtime.tool_manager.execute(
            ToolCall(
                id="call-create-todo",
                name="create_todo",
                arguments=json.dumps({"title": "Ship tools"}),
            )
        )
        todo_payload = json.loads(create_todo_result.content or "{}")
        todo_id = todo_payload["todo"]["todo_id"]

        list_todos_result = await runtime.tool_manager.execute(
            ToolCall(
                id="call-list-todos",
                name="list_todos",
                arguments=json.dumps({}),
            )
        )
        list_payload = json.loads(list_todos_result.content or "{}")
        assert list_payload["todos"][0]["todo_id"] == todo_id

        complete_todo_result = await runtime.tool_manager.execute(
            ToolCall(
                id="call-complete-todo",
                name="complete_todo",
                arguments=json.dumps({"todo_id": todo_id}),
            )
        )
        complete_payload = json.loads(complete_todo_result.content or "{}")
        assert complete_payload["todo"]["completed"] is True
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


async def _run_code_interpreter_requires_sandbox_registration() -> None:
    runtime = await build_cyrene_ai_runtime(
        register_builtin_plugins=False,
        tool_sandbox_mode="in_process",
    )
    try:
        assert runtime.tool_registry is not None
        assert runtime.tool_registry.exists("code_interpreter")
    finally:
        await runtime.close()


def test_code_interpreter_requires_sandbox_registration() -> None:
    asyncio.run(_run_code_interpreter_requires_sandbox_registration())


def test_current_time_supports_unix_format_and_validates_options() -> None:
    async def run() -> None:
        manager = _builtin_tool_manager()

        result = await manager.execute(
            _tool_call(
                "get_current_time",
                {"utc_offset": "-05:30", "format": "unix"},
            )
        )
        payload = json.loads(result.content or "{}")
        assert payload["utc_offset"] == "-05:30"
        assert "unix" in payload

        invalid_calls = [
            ({"format": "bad"}, r"arguments.format must be one of"),
            ({"utc_offset": 8}, "arguments.utc_offset has invalid type"),
            ({"utc_offset": "8"}, "utc_offset must match"),
            ({"utc_offset": "+24:00"}, "utc_offset is out of range"),
        ]
        for arguments, message in invalid_calls:
            with pytest.raises((ToolExecutionError, ToolInputError), match=message):
                await manager.execute(_tool_call("get_current_time", arguments))

    asyncio.run(run())


def test_current_time_executor_validates_format_after_argument_parse() -> None:
    async def run() -> None:
        executor = builtin._CurrentTimeToolExecutor()

        with pytest.raises(ToolExecutionError, match="format must be iso or unix"):
            await executor.execute(_tool_call("get_current_time", {"format": "bad"}))

    asyncio.run(run())


def test_calculate_covers_math_functions_and_rejects_bad_expressions() -> None:
    async def run() -> None:
        manager = _builtin_tool_manager()

        result = await manager.execute(
            _tool_call(
                "calculate",
                {
                    "expression": (
                        "abs(-2)+ceil(1.2)+floor(1.8)+max(1, 3)+min(1, 3)"
                        "+pow(2, 3)+round(1.26, 1)+pi-pi"
                    )
                },
            )
        )
        payload = json.loads(result.content or "{}")
        assert payload["result"] == 18.3

        invalid_expressions = [
            ("1+", "expression must be valid arithmetic"),
            ("'x'", "expression constants must be numbers"),
            ("unknown", "unknown constant"),
            ("10**13", "exponent is too large"),
            ("1/0", "calculation failed"),
            ("sqrt(-1)", "calculation failed"),
            ("round(value=1)", "keyword arguments are not supported"),
            ("sum(1)", "unknown function"),
            ("(1).__str__()", "only direct math function calls are allowed"),
            ("max(1,2,3,4,5,6,7,8,9)", "too many function arguments"),
            ("[1]", "unsupported expression node"),
            ("1 << 2", "unsupported arithmetic operator"),
            ("~1", "unsupported unary operator"),
            ("1000000000001", "expression number is too large"),
            ("1000000000000*10000", "calculation result is too large"),
            ("9" * 513, "expression is too large"),
        ]
        for expression, message in invalid_expressions:
            with pytest.raises(ToolExecutionError, match=message):
                await manager.execute(
                    _tool_call("calculate", {"expression": expression})
                )

    asyncio.run(run())


def test_json_get_covers_root_and_path_errors() -> None:
    async def run() -> None:
        manager = _builtin_tool_manager()

        root_result = await manager.execute(
            _tool_call("json_get", {"json": json.dumps({"ok": True})})
        )
        assert json.loads(root_result.content or "{}") == {
            "path": "",
            "value": {"ok": True},
        }

        invalid_calls = [
            ({"json": "{"}, "json must be valid JSON"),
            ({"json": "{}", "path": 123}, "arguments.path has invalid type"),
            ({"json": "{}", "path": "."}, "path cannot contain empty segments"),
            ({"json": "{}", "path": "missing"}, "path segment not found"),
            ({"json": "[1]", "path": "name"}, "list path segment must be an index"),
            ({"json": "[1]", "path": "1"}, "list index out of range"),
            ({"json": "1", "path": "x"}, "path cannot descend into"),
            (
                {"json": "{}", "path": ".".join(["x"] * 65)},
                "path is too deep",
            ),
        ]
        for arguments, message in invalid_calls:
            with pytest.raises((ToolExecutionError, ToolInputError), match=message):
                await manager.execute(_tool_call("json_get", arguments))

    asyncio.run(run())


def test_text_search_covers_regex_and_validation_errors() -> None:
    async def run() -> None:
        manager = _builtin_tool_manager()

        regex_result = await manager.execute(
            _tool_call(
                "text_search",
                {
                    "text": "Alpha beta ALPHA",
                    "query": "alpha",
                    "regex": True,
                    "case_sensitive": False,
                    "max_matches": 10,
                },
            )
        )
        regex_payload = json.loads(regex_result.content or "{}")
        assert regex_payload["match_count"] == 2
        assert [match["match"] for match in regex_payload["matches"]] == [
            "Alpha",
            "ALPHA",
        ]

        case_result = await manager.execute(
            _tool_call(
                "text_search",
                {
                    "text": "Alpha alpha",
                    "query": "alpha",
                    "case_sensitive": True,
                },
            )
        )
        case_payload = json.loads(case_result.content or "{}")
        assert case_payload["match_count"] == 1
        assert case_payload["matches"][0]["start"] == 6

        invalid_calls = [
            ({"text": "x", "query": "[", "regex": True}, "valid regular expression"),
            ({"text": "x", "query": "x", "regex": "yes"}, "arguments.regex has invalid type"),
            (
                {"text": "x", "query": "x", "case_sensitive": "yes"},
                "arguments.case_sensitive has invalid type",
            ),
            (
                {"text": "x", "query": "x", "max_matches": True},
                "arguments.max_matches has invalid type",
            ),
            ({"text": "x", "query": "x", "max_matches": 0}, "positive integer"),
        ]
        for arguments, message in invalid_calls:
            with pytest.raises((ToolExecutionError, ToolInputError), match=message):
                await manager.execute(_tool_call("text_search", arguments))

    asyncio.run(run())


def test_builtin_tool_argument_parsing_errors() -> None:
    async def run() -> None:
        manager = _builtin_tool_manager()

        with pytest.raises(ToolInputError, match="valid JSON"):
            await manager.execute(_tool_call("calculate", "{"))

        with pytest.raises(ToolInputError, match="JSON object"):
            await manager.execute(_tool_call("calculate", "[]"))

        with pytest.raises(ToolInputError, match="arguments.expression is required"):
            await manager.execute(_tool_call("calculate", {}))

    asyncio.run(run())


def test_todo_tools_cover_filters_and_validation_errors() -> None:
    async def run() -> None:
        manager = _builtin_tool_manager()

        first = await manager.execute(
            _tool_call(
                "create_todo",
                {
                    "title": " First ",
                    "due_at": " 2026-06-13 ",
                    "tags": [" work ", "", "ship"],
                },
            )
        )
        first_id = json.loads(first.content or "{}")["todo"]["todo_id"]
        second = await manager.execute(
            _tool_call("create_todo", {"title": "Second"})
        )
        second_id = json.loads(second.content or "{}")["todo"]["todo_id"]

        await manager.execute(_tool_call("complete_todo", {"todo_id": first_id}))

        active = await manager.execute(_tool_call("list_todos", {"limit": 1}))
        active_payload = json.loads(active.content or "{}")
        assert active_payload["count"] == 1
        assert active_payload["todos"][0]["todo_id"] == second_id

        all_todos = await manager.execute(
            _tool_call("list_todos", {"include_completed": True, "limit": 1000})
        )
        all_payload = json.loads(all_todos.content or "{}")
        assert all_payload["count"] == 2
        assert all_payload["todos"][0]["tags"] == ["work", "ship"]

        invalid_calls = [
            ("create_todo", {"title": "x", "due_at": 123}, "arguments.due_at has invalid type"),
            ("create_todo", {"title": "x", "tags": "work"}, "arguments.tags has invalid type"),
            (
                "create_todo",
                {"title": "x", "tags": [123]},
                r"arguments.tags\[0\] has invalid type",
            ),
            (
                "list_todos",
                {"include_completed": "yes"},
                "arguments.include_completed has invalid type",
            ),
            ("list_todos", {"limit": True}, "arguments.limit has invalid type"),
            ("list_todos", {"limit": 0}, "positive integer"),
            ("complete_todo", {"todo_id": "missing"}, "todo_id not found"),
        ]
        for name, arguments, message in invalid_calls:
            with pytest.raises((ToolExecutionError, ToolInputError), match=message):
                await manager.execute(_tool_call(name, arguments))

    asyncio.run(run())


def test_todo_executor_helpers_validate_after_argument_parse() -> None:
    async def run() -> None:
        store: dict = {}
        create_executor = todo._CreateTodoToolExecutor(store)
        list_executor = todo._ListTodosToolExecutor(store)

        invalid_create_calls = [
            ({"title": "x", "due_at": 123}, "value must be a string"),
            ({"title": "x", "tags": "work"}, "tags must be an array"),
            ({"title": "x", "tags": [123]}, "tags must contain only strings"),
        ]
        for arguments, message in invalid_create_calls:
            with pytest.raises(ToolExecutionError, match=message):
                await create_executor.execute(_tool_call("create_todo", arguments))

        invalid_list_calls = [
            ({"include_completed": "yes"}, "value must be a boolean"),
            ({"limit": True}, "value must be a positive integer"),
        ]
        for arguments, message in invalid_list_calls:
            with pytest.raises(ToolExecutionError, match=message):
                await list_executor.execute(_tool_call("list_todos", arguments))

        with pytest.raises(ToolExecutionError, match="Tool arguments must be valid JSON"):
            await create_executor.execute(_tool_call("create_todo", "{"))

        with pytest.raises(ToolExecutionError, match="Tool arguments must be a JSON object"):
            await create_executor.execute(_tool_call("create_todo", "[]"))

    asyncio.run(run())
