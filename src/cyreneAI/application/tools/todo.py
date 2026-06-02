from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from cyreneAI.core.errors.tool import ToolExecutionError
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolDefinition,
    ToolPermission,
    ToolResult,
    ToolRiskLevel,
    ToolSafetyProfile,
)
from cyreneAI.core.tool.tool_protocol import ToolExecutorProtocol, ToolRegistryProtocol


def register_todo_tools(registry: ToolRegistryProtocol) -> None:
    """
    Register simple in-memory todo tools for agent-visible task tracking.
    """
    store: dict[str, dict[str, Any]] = {}
    _register_if_missing(
        registry,
        ToolDefinition(
            name="create_todo",
            description="Create a todo item with optional due time and tags.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "due_at": {
                        "type": "string",
                        "description": "Optional ISO-like due date/time text.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["title"],
                "additionalProperties": False,
            },
            safety_profile=ToolSafetyProfile(
                risk_level=ToolRiskLevel.WRITE,
                permissions=[ToolPermission.MEMORY_WRITE],
                timeout_seconds=2,
                max_output_chars=4096,
            ),
            metadata={"source": "builtin"},
        ),
        _CreateTodoToolExecutor(store),
    )
    _register_if_missing(
        registry,
        ToolDefinition(
            name="list_todos",
            description="List active or completed todo items.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "include_completed": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            safety_profile=ToolSafetyProfile(
                risk_level=ToolRiskLevel.READ_ONLY,
                permissions=[ToolPermission.MEMORY_READ],
                timeout_seconds=2,
                max_output_chars=16384,
            ),
            metadata={"source": "builtin"},
        ),
        _ListTodosToolExecutor(store),
    )
    _register_if_missing(
        registry,
        ToolDefinition(
            name="complete_todo",
            description="Mark a todo item as completed.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "todo_id": {"type": "string"},
                },
                "required": ["todo_id"],
                "additionalProperties": False,
            },
            safety_profile=ToolSafetyProfile(
                risk_level=ToolRiskLevel.WRITE,
                permissions=[ToolPermission.MEMORY_WRITE],
                timeout_seconds=2,
                max_output_chars=4096,
            ),
            metadata={"source": "builtin"},
        ),
        _CompleteTodoToolExecutor(store),
    )


class _CreateTodoToolExecutor:
    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self._store = store

    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = _parse_arguments(call)
        title = _required_string(arguments, "title")
        tags = _optional_string_list(arguments.get("tags"))
        todo_id = uuid4().hex
        todo = {
            "todo_id": todo_id,
            "title": title,
            "due_at": _optional_string(arguments.get("due_at")),
            "tags": tags,
            "completed": False,
            "created_at": datetime.now(UTC).isoformat(),
            "completed_at": None,
        }
        self._store[todo_id] = todo
        return _json_result(call, {"todo": todo})


class _ListTodosToolExecutor:
    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self._store = store

    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = _parse_arguments(call)
        include_completed = _optional_bool(
            arguments.get("include_completed"),
            default=False,
        )
        limit = _positive_int(arguments.get("limit"), default=20, maximum=100)
        todos = [
            todo
            for todo in self._store.values()
            if include_completed or not bool(todo.get("completed"))
        ]
        todos.sort(key=lambda item: str(item.get("created_at", "")))
        return _json_result(
            call,
            {
                "count": len(todos[:limit]),
                "todos": todos[:limit],
            },
        )


class _CompleteTodoToolExecutor:
    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self._store = store

    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = _parse_arguments(call)
        todo_id = _required_string(arguments, "todo_id")
        todo = self._store.get(todo_id)
        if todo is None:
            raise ToolExecutionError(f"todo_id not found: {todo_id}")
        todo["completed"] = True
        todo["completed_at"] = datetime.now(UTC).isoformat()
        return _json_result(call, {"todo": todo})


def _register_if_missing(
    registry: ToolRegistryProtocol,
    definition: ToolDefinition,
    executor: ToolExecutorProtocol,
) -> None:
    if registry.exists(definition.name):
        return
    registry.register(definition, executor)


def _parse_arguments(call: ToolCall) -> dict[str, Any]:
    if not call.arguments:
        return {}
    try:
        parsed = json.loads(call.arguments)
    except json.JSONDecodeError as exc:
        raise ToolExecutionError("Tool arguments must be valid JSON", cause=exc) from exc
    if not isinstance(parsed, dict):
        raise ToolExecutionError("Tool arguments must be a JSON object")
    return cast(dict[str, Any], parsed)


def _required_string(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolExecutionError(f"{name} is required")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolExecutionError("value must be a string")
    stripped = value.strip()
    return stripped or None


def _optional_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ToolExecutionError("tags must be an array")
    tags: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ToolExecutionError("tags must contain only strings")
        stripped = item.strip()
        if stripped:
            tags.append(stripped)
    return tags


def _optional_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ToolExecutionError("value must be a boolean")
    return value


def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ToolExecutionError("value must be a positive integer")
    return min(value, maximum)


def _json_result(call: ToolCall, payload: dict[str, Any]) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )


__all__ = ["register_todo_tools"]
