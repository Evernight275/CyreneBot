from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, cast
from uuid import uuid4

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.application.tools.execution_context import get_tool_execution_context
from cyreneAI.core.errors.base import StateError
from cyreneAI.core.errors.tool import ToolExecutionError
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolDefinition,
    ToolPermission,
    ToolResult,
    ToolRiskLevel,
    ToolSafetyProfile,
)
from cyreneAI.core.schema.vector import VectorQuery, VectorRecord
from cyreneAI.core.tool.tool_protocol import ToolExecutorProtocol, ToolRegistryProtocol
from cyreneAI.core.vector.manager import VectorManager


_MEMORY_KIND = "agent_memory"
_DEFAULT_NAMESPACE = "default"
_VECTOR_DIMENSIONS = 64


def register_memory_tools(runtime: CyreneAIRuntime) -> None:
    if runtime.tool_registry is None or runtime.vector_manager is None:
        return

    _register_if_missing(
        runtime.tool_registry,
        ToolDefinition(
            name="remember_fact",
            description=(
                "Store a durable memory fact for later agent runs. "
                "Use it for stable user preferences, project facts, and decisions."
            ),
            safety_profile=ToolSafetyProfile(
                risk_level=ToolRiskLevel.WRITE,
                permissions=[ToolPermission.MEMORY_WRITE],
                timeout_seconds=5,
                max_output_chars=4096,
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The memory content to store.",
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Optional memory namespace; defaults to session_id.",
                    },
                    "memory_id": {
                        "type": "string",
                        "description": "Optional stable memory id for updates.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "metadata": {
                        "type": "object",
                    },
                },
                "required": ["content"],
                "additionalProperties": False,
            },
        ),
        _RememberFactToolExecutor(runtime.vector_manager),
    )
    _register_if_missing(
        runtime.tool_registry,
        ToolDefinition(
            name="search_memory",
            description=(
                "Search durable memory facts by query. "
                "Use it before answering questions that may depend on prior context."
            ),
            safety_profile=ToolSafetyProfile(
                risk_level=ToolRiskLevel.READ_ONLY,
                permissions=[ToolPermission.MEMORY_READ],
                timeout_seconds=5,
                max_output_chars=16384,
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search text.",
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Optional memory namespace; defaults to session_id.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of matches.",
                    },
                    "min_score": {
                        "type": "number",
                        "description": "Optional minimum similarity score.",
                    },
                    "filters": {
                        "type": "object",
                        "description": "Additional exact metadata filters.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        _SearchMemoryToolExecutor(runtime.vector_manager),
    )
    _register_if_missing(
        runtime.tool_registry,
        ToolDefinition(
            name="get_memory",
            description="Get a durable memory fact by memory_id.",
            safety_profile=ToolSafetyProfile(
                risk_level=ToolRiskLevel.READ_ONLY,
                permissions=[ToolPermission.MEMORY_READ],
                timeout_seconds=5,
                max_output_chars=8192,
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                },
                "required": ["memory_id"],
                "additionalProperties": False,
            },
        ),
        _GetMemoryToolExecutor(runtime.vector_manager),
    )
    _register_if_missing(
        runtime.tool_registry,
        ToolDefinition(
            name="forget_memory",
            description="Delete a durable memory fact by memory_id.",
            safety_profile=ToolSafetyProfile(
                risk_level=ToolRiskLevel.WRITE,
                permissions=[ToolPermission.MEMORY_WRITE],
                timeout_seconds=5,
                max_output_chars=4096,
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                },
                "required": ["memory_id"],
                "additionalProperties": False,
            },
        ),
        _ForgetMemoryToolExecutor(runtime.vector_manager),
    )


class _RememberFactToolExecutor:
    def __init__(self, vector_manager: VectorManager) -> None:
        self._vector_manager = vector_manager

    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = _parse_arguments(call)
        content = _required_string(arguments, "content")
        namespace = _namespace(arguments.get("namespace"))
        memory_id = _memory_id(arguments.get("memory_id"), namespace=namespace)
        tags = _string_list(arguments.get("tags"))
        extra_metadata = _object(arguments.get("metadata"))
        context = get_tool_execution_context()

        metadata: dict[str, Any] = {
            **extra_metadata,
            "kind": _MEMORY_KIND,
            "namespace": namespace,
            "tags": tags,
        }
        if context is not None:
            metadata.update(
                {
                    "session_id": context.session_id,
                    "provider_id": context.provider_id,
                    "model": context.model,
                }
            )

        await self._vector_manager.upsert(
            [
                VectorRecord(
                    record_id=memory_id,
                    vector=_text_vector(content),
                    content=content,
                    metadata=metadata,
                )
            ]
        )
        return _json_result(
            call,
            {
                "memory_id": memory_id,
                "namespace": namespace,
                "stored": True,
            },
        )


class _SearchMemoryToolExecutor:
    def __init__(self, vector_manager: VectorManager) -> None:
        self._vector_manager = vector_manager

    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = _parse_arguments(call)
        query = _required_string(arguments, "query")
        namespace = _namespace(arguments.get("namespace"))
        top_k = _positive_int(arguments.get("top_k"), default=5, maximum=20)
        min_score = _optional_float(arguments.get("min_score"))
        extra_filters = _object(arguments.get("filters"))
        filters: dict[str, Any] = {
            **extra_filters,
            "kind": _MEMORY_KIND,
            "namespace": namespace,
        }

        result = await self._vector_manager.search(
            VectorQuery(
                vector=_text_vector(query),
                top_k=top_k,
                filters=filters,
                min_score=min_score,
            )
        )
        return _json_result(
            call,
            {
                "query": query,
                "namespace": namespace,
                "matches": [
                    {
                        "memory_id": match.record.record_id,
                        "content": match.record.content,
                        "score": match.score,
                        "metadata": match.record.metadata,
                    }
                    for match in result.matches
                ],
                "metadata": result.metadata,
            },
        )


class _GetMemoryToolExecutor:
    def __init__(self, vector_manager: VectorManager) -> None:
        self._vector_manager = vector_manager

    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = _parse_arguments(call)
        memory_id = _required_string(arguments, "memory_id")
        record = await self._vector_manager.get(memory_id)
        _ensure_memory_record(record)
        return _json_result(
            call,
            {
                "memory_id": record.record_id,
                "content": record.content,
                "metadata": record.metadata,
            },
        )


class _ForgetMemoryToolExecutor:
    def __init__(self, vector_manager: VectorManager) -> None:
        self._vector_manager = vector_manager

    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = _parse_arguments(call)
        memory_id = _required_string(arguments, "memory_id")
        record = await self._vector_manager.get(memory_id)
        _ensure_memory_record(record)
        await self._vector_manager.delete(memory_id)
        return _json_result(
            call,
            {
                "memory_id": memory_id,
                "deleted": True,
            },
        )


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


def _namespace(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    context = get_tool_execution_context()
    if context is not None and context.session_id:
        return context.session_id
    return _DEFAULT_NAMESPACE


def _memory_id(value: Any, *, namespace: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    safe_namespace = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", namespace).strip("_")
    if not safe_namespace:
        safe_namespace = _DEFAULT_NAMESPACE
    return f"memory:{safe_namespace}:{uuid4()}"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ToolExecutionError("tags must be an array")
    tags: list[str] = []
    values = cast(list[Any], value)
    for item in values:
        if not isinstance(item, str):
            raise ToolExecutionError("tags must contain only strings")
        tag = item.strip()
        if tag:
            tags.append(tag)
    return tags


def _object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ToolExecutionError("metadata filters must be objects")
    return cast(dict[str, Any], value)


def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ToolExecutionError("top_k must be a positive integer")
    return min(value, maximum)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ToolExecutionError("min_score must be a number")
    return float(value)


def _ensure_memory_record(record: VectorRecord) -> None:
    if record.metadata.get("kind") != _MEMORY_KIND:
        raise ToolExecutionError("Record is not a memory record")


def _text_vector(text: str) -> list[float]:
    vector = [0.0] * _VECTOR_DIMENSIONS
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % _VECTOR_DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        vector[0] = 1.0
        return vector
    return [value / norm for value in vector]


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[\w\u4e00-\u9fff]+", text, flags=re.UNICODE)
        if token.strip()
    ]


def _json_result(call: ToolCall, payload: dict[str, Any]) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )


__all__ = ["register_memory_tools"]
