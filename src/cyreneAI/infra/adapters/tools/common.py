from __future__ import annotations

import json
from typing import Any, cast

from cyreneAI.core.errors.tool import ToolInputError
from cyreneAI.core.schema.tool import ToolCall, ToolResult

ToolResultPayload = ToolResult | str | dict[str, Any]


def parse_tool_arguments(arguments: str | None) -> dict[str, Any]:
    """
    解析工具调用参数
    """
    if not arguments:
        return {}

    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise ToolInputError("Tool arguments must be valid JSON", cause=exc) from exc

    if not isinstance(parsed, dict):
        raise ToolInputError("Tool arguments must be a JSON object")
    return cast(dict[str, Any], parsed)


def map_tool_result(
    call: ToolCall,
    result: ToolResultPayload,
) -> ToolResult:
    """
    将通用工具返回值映射为 ToolResult
    """
    if isinstance(result, ToolResult):
        return result.model_copy(
            update={
                "call_id": call.id,
                "name": call.name,
            }
        )

    content = (
        json.dumps(result, ensure_ascii=False)
        if isinstance(result, dict)
        else str(result)
    )
    return ToolResult(
        call_id=call.id,
        name=call.name,
        content=content,
    )


def map_tool_result_object(call: ToolCall, payload: dict[str, Any]) -> ToolResult:
    """
    将约定式 JSON 对象映射为 ToolResult
    """
    if _looks_like_tool_result(payload):
        metadata = payload.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            metadata = {"value": metadata}

        content = payload.get("content")
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=_stringify_content(content),
            success=bool(payload.get("success", True)),
            error=_stringify_error(payload.get("error")),
            metadata=metadata or {},
        )

    return map_tool_result(call, payload)


def map_json_text_tool_result(call: ToolCall, text: str) -> ToolResult:
    """
    将文本响应映射为 ToolResult，优先识别 JSON 对象
    """
    stripped = text.strip()
    if not stripped:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content="",
        )

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return map_tool_result(call, stripped)

    if isinstance(parsed, dict):
        return map_tool_result_object(call, cast(dict[str, Any], parsed))
    return map_tool_result(call, stripped)


def make_tool_payload(call: ToolCall, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    构造发送给外部工具后端的标准 payload
    """
    return {
        "id": call.id,
        "name": call.name,
        "arguments": arguments,
    }


def decode_process_output(data: bytes) -> str:
    """
    Decode subprocess output into a stable cross-platform text form.
    """
    return (
        data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    )


def _looks_like_tool_result(payload: dict[str, Any]) -> bool:
    return any(
        key in payload
        for key in (
            "call_id",
            "content",
            "success",
            "error",
            "metadata",
        )
    )


def _stringify_content(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _stringify_error(error: Any) -> str | None:
    if error is None:
        return None
    return str(error)
