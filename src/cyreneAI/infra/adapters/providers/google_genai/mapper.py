from __future__ import annotations

import json
from typing import Any

from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest, ChatResponse
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.tool import ToolCall, ToolChoice, ToolDefinition
from cyreneAI.core.schema.usage import TokenUsage


def map_google_genai_request(request: ChatRequest) -> dict[str, Any]:
    config: dict[str, Any] = {
        "temperature": request.temperature,
        "top_p": request.top_p,
        "max_output_tokens": request.max_tokens,
        "tools": map_tools(request.tools),
        "tool_config": map_tool_config(request.tool_choice),
    }
    return {
        "model": request.model,
        "contents": [map_content(message) for message in request.messages],
        "config": _drop_none(config),
    }


def map_content(message: Message) -> dict[str, Any]:
    return {
        "role": map_role(message.role),
        "parts": map_parts(message),
    }


def map_role(role: MessageRole) -> str:
    if role == MessageRole.ASSISTANT:
        return "model"
    return "user"


def map_parts(message: Message) -> list[dict[str, Any]]:
    if message.role == MessageRole.TOOL:
        return [
            {
                "function_response": {
                    "name": message.name or "",
                    "response": {
                        "result": map_content_parts(message.content),
                    },
                }
            }
        ]

    text = map_content_parts(message.content)
    return [{"text": text}] if text else []


def map_content_parts(parts: list[ContentPart] | None) -> str:
    if not parts:
        return ""
    texts = [
        part.text
        for part in parts
        if part.type == ContentPartType.TEXT and part.text is not None
    ]
    return "\n".join(texts)


def map_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters_json_schema": tool.parameters_schema
        or {
            "type": "object",
            "properties": {},
        },
    }


def map_tools(tools: list[ToolDefinition] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "function_declarations": [map_tool(tool) for tool in tools],
        }
    ]


def map_tool_config(tool_choice: ToolChoice | None) -> dict[str, Any] | None:
    if tool_choice is None:
        return None

    if tool_choice.mode == "auto":
        mode = "AUTO"
    elif tool_choice.mode == "none":
        mode = "NONE"
    else:
        mode = "ANY"

    config: dict[str, Any] = {
        "function_calling_config": {
            "mode": mode,
        }
    }
    if tool_choice.mode == "tool" and tool_choice.name:
        config["function_calling_config"]["allowed_function_names"] = [
            tool_choice.name
        ]
    return config


def map_google_genai_response(provider_id: str, response: Any) -> ChatResponse:
    candidates = getattr(response, "candidates", None) or []
    candidate = candidates[0] if candidates else None
    parts = []
    if candidate is not None and getattr(candidate, "content", None) is not None:
        parts = getattr(candidate.content, "parts", None) or []

    text = map_response_text(parts)
    tool_calls = [
        tool_call
        for tool_call in (map_tool_call(part) for part in parts)
        if tool_call is not None
    ]

    return ChatResponse(
        provider_id=provider_id,
        model=getattr(response, "model_version", None),
        message=(
            Message(
                role=MessageRole.ASSISTANT,
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text=text,
                    )
                ],
            )
            if text
            else None
        ),
        tool_calls=tool_calls,
        finish_reason=map_finish_reason(candidate, tool_calls),
        usage=map_usage(getattr(response, "usage_metadata", None)),
        raw=response.model_dump(mode="json") if hasattr(response, "model_dump") else None,
    )


def map_response_text(parts: list[Any]) -> str | None:
    texts = [
        getattr(part, "text", None)
        for part in parts
        if getattr(part, "text", None)
    ]
    if not texts:
        return None
    return "\n".join(texts)


def map_tool_call(part: Any) -> ToolCall | None:
    function_call = getattr(part, "function_call", None)
    if function_call is None:
        return None
    return ToolCall(
        id=getattr(function_call, "id", "") or getattr(function_call, "name", ""),
        name=getattr(function_call, "name", ""),
        arguments=map_tool_arguments(getattr(function_call, "args", None)),
    )


def map_tool_arguments(arguments: Any) -> str | None:
    if arguments is None:
        return None
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments, ensure_ascii=False)


def map_finish_reason(candidate: Any | None, tool_calls: list[ToolCall]) -> ChatFinishReason:
    if tool_calls:
        return ChatFinishReason.TOOL_CALLS
    reason = getattr(candidate, "finish_reason", None)
    if reason is None:
        return ChatFinishReason.UNKNOWN
    reason_value = getattr(reason, "value", str(reason))
    if reason_value == "STOP":
        return ChatFinishReason.STOP
    if reason_value == "MAX_TOKENS":
        return ChatFinishReason.LENGTH
    return ChatFinishReason.UNKNOWN


def map_usage(usage: Any | None) -> TokenUsage | None:
    if usage is None:
        return None
    return TokenUsage(
        prompt_tokens=getattr(usage, "prompt_token_count", None),
        completion_tokens=getattr(usage, "candidates_token_count", None),
        total_tokens=getattr(usage, "total_token_count", None),
    )


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
