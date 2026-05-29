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


def map_anthropic_request(request: ChatRequest) -> dict[str, Any]:
    system = map_system_messages(request.messages)
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [
            map_message(message)
            for message in request.messages
            if message.role != MessageRole.SYSTEM
        ],
        "max_tokens": request.max_tokens or 1024,
        "temperature": request.temperature,
        "top_p": request.top_p,
        "tools": map_tools(request.tools),
        "tool_choice": map_tool_choice(request.tool_choice),
        "system": system,
    }
    return _drop_none(payload)


def map_message(message: Message) -> dict[str, Any]:
    if message.role == MessageRole.TOOL:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": map_content_parts(message.content),
                }
            ],
        }

    role = "assistant" if message.role == MessageRole.ASSISTANT else "user"
    if message.role == MessageRole.ASSISTANT and message.tool_calls:
        return {
            "role": role,
            "content": [
                *map_text_content_blocks(message.content),
                *map_tool_use_blocks(message.tool_calls),
            ],
        }
    return {
        "role": role,
        "content": map_content_parts(message.content),
    }


def map_system_messages(messages: list[Message]) -> str | None:
    texts = [
        text
        for message in messages
        if message.role == MessageRole.SYSTEM
        for text in [map_content_parts(message.content)]
        if text
    ]
    if not texts:
        return None
    return "\n".join(texts)


def map_content_parts(parts: list[ContentPart] | None) -> str:
    if not parts:
        return ""
    texts = [
        part.text
        for part in parts
        if part.type == ContentPartType.TEXT and part.text is not None
    ]
    return "\n".join(texts)


def map_text_content_blocks(parts: list[ContentPart] | None) -> list[dict[str, Any]]:
    text = map_content_parts(parts)
    if not text:
        return []
    return [
        {
            "type": "text",
            "text": text,
        }
    ]


def map_tool_use_blocks(tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
    return [
        {
            "type": "tool_use",
            "id": tool_call.id,
            "name": tool_call.name,
            "input": map_tool_input(tool_call.arguments),
        }
        for tool_call in tool_calls
    ]


def map_tool_input(arguments: str | None) -> Any:
    if not arguments:
        return {}
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return {"value": arguments}


def map_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters_schema
        or {
            "type": "object",
            "properties": {},
        },
    }


def map_tools(tools: list[ToolDefinition] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [map_tool(tool) for tool in tools]


def map_tool_choice(tool_choice: ToolChoice | None) -> dict[str, Any] | None:
    if tool_choice is None:
        return None
    if tool_choice.mode in {"auto", "none"}:
        return {"type": tool_choice.mode}
    if tool_choice.mode == "required":
        return {"type": "any"}
    if tool_choice.mode == "tool" and tool_choice.name:
        return {
            "type": "tool",
            "name": tool_choice.name,
        }
    return None


def map_anthropic_response(provider_id: str, response: Any) -> ChatResponse:
    content = getattr(response, "content", None) or []
    text = map_response_text(content)
    tool_calls = [
        tool_call
        for tool_call in (map_tool_call(block) for block in content)
        if tool_call is not None
    ]

    return ChatResponse(
        provider_id=provider_id,
        model=getattr(response, "model", None),
        message=(
            Message(
                role=MessageRole.ASSISTANT,
                content=(
                    [
                        ContentPart(
                            type=ContentPartType.TEXT,
                            text=text,
                        )
                    ]
                    if text
                    else None
                ),
                tool_calls=tool_calls or None,
            )
            if text or tool_calls
            else None
        ),
        tool_calls=tool_calls,
        finish_reason=map_finish_reason(getattr(response, "stop_reason", None)),
        usage=map_usage(getattr(response, "usage", None)),
        raw=response.model_dump(mode="json") if hasattr(response, "model_dump") else None,
    )


def map_response_text(content: list[Any]) -> str | None:
    texts = [
        getattr(block, "text", None)
        for block in content
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    ]
    if not texts:
        return None
    return "\n".join(texts)


def map_tool_call(block: Any) -> ToolCall | None:
    if getattr(block, "type", None) != "tool_use":
        return None
    return ToolCall(
        id=getattr(block, "id", ""),
        name=getattr(block, "name", ""),
        arguments=map_tool_arguments(getattr(block, "input", None)),
    )


def map_tool_arguments(arguments: Any) -> str | None:
    if arguments is None:
        return None
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments, ensure_ascii=False)


def map_finish_reason(reason: str | None) -> ChatFinishReason:
    if reason == "end_turn":
        return ChatFinishReason.STOP
    if reason == "max_tokens":
        return ChatFinishReason.LENGTH
    if reason == "tool_use":
        return ChatFinishReason.TOOL_CALLS
    return ChatFinishReason.UNKNOWN


def map_usage(usage: Any | None) -> TokenUsage | None:
    if usage is None:
        return None
    return TokenUsage(
        prompt_tokens=getattr(usage, "input_tokens", None),
        completion_tokens=getattr(usage, "output_tokens", None),
        total_tokens=(
            getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0)
        ),
    )


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
