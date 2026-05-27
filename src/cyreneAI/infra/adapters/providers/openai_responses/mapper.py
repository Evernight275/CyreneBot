from __future__ import annotations

from typing import Any

from cyreneAI.core.schema.chat import (
    ChatFinishReason,
    ChatRequest,
    ChatResponse,
)
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.tool import ToolCall, ToolChoice, ToolDefinition
from cyreneAI.core.schema.usage import TokenUsage


def map_responses_request(request: ChatRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "input": [map_input_message(message) for message in request.messages],
        "temperature": request.temperature,
        "max_output_tokens": request.max_tokens,
        "top_p": request.top_p,
        "tools": map_tools(request.tools),
        "tool_choice": map_tool_choice(request.tool_choice),
    }
    return _drop_none(payload)


def map_input_message(message: Message) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": map_message_role(message.role),
        "content": map_content_parts(message.content),
    }
    return _drop_none(payload)


def map_message_role(role: MessageRole) -> str:
    if role == MessageRole.TOOL:
        return "user"
    return role.value


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
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters_schema
        or {
            "type": "object",
            "properties": {},
        },
        "strict": None,
    }


def map_tools(tools: list[ToolDefinition] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [map_tool(tool) for tool in tools]


def map_tool_choice(tool_choice: ToolChoice | None) -> str | dict[str, Any] | None:
    if tool_choice is None:
        return None

    if tool_choice.mode in {"auto", "none", "required"}:
        return tool_choice.mode

    if tool_choice.mode == "tool" and tool_choice.name:
        return {
            "type": "function",
            "name": tool_choice.name,
        }

    return None


def map_responses_response(provider_id: str, response: Any) -> ChatResponse:
    output = getattr(response, "output", None) or []
    tool_calls = [
        tool_call
        for tool_call in (map_tool_call(item) for item in output)
        if tool_call is not None
    ]
    content_text = map_output_text(output)

    return ChatResponse(
        provider_id=provider_id,
        model=getattr(response, "model", None),
        message=(
            Message(
                role=MessageRole.ASSISTANT,
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text=content_text,
                    )
                ],
            )
            if content_text
            else None
        ),
        tool_calls=tool_calls,
        finish_reason=map_finish_reason(response, tool_calls),
        usage=map_usage(getattr(response, "usage", None)),
        raw=response.model_dump(mode="json") if hasattr(response, "model_dump") else None,
    )


def map_output_text(output: list[Any]) -> str | None:
    texts: list[str] = []
    for item in output:
        if getattr(item, "type", None) != "message":
            continue

        for content in getattr(item, "content", None) or []:
            text = getattr(content, "text", None)
            if text:
                texts.append(text)

    if not texts:
        return None
    return "\n".join(texts)


def map_tool_call(item: Any) -> ToolCall | None:
    if getattr(item, "type", None) != "function_call":
        return None

    return ToolCall(
        id=getattr(item, "call_id", "") or getattr(item, "id", ""),
        name=getattr(item, "name", ""),
        arguments=getattr(item, "arguments", None),
    )


def map_finish_reason(response: Any, tool_calls: list[ToolCall]) -> ChatFinishReason:
    if tool_calls:
        return ChatFinishReason.TOOL_CALLS

    status = getattr(response, "status", None)
    incomplete_details = getattr(response, "incomplete_details", None)
    incomplete_reason = getattr(incomplete_details, "reason", None)

    if status == "incomplete" and incomplete_reason == "max_output_tokens":
        return ChatFinishReason.LENGTH
    if status == "completed":
        return ChatFinishReason.STOP
    return ChatFinishReason.UNKNOWN


def map_usage(usage: Any | None) -> TokenUsage | None:
    if usage is None:
        return None

    return TokenUsage(
        prompt_tokens=getattr(usage, "input_tokens", None),
        completion_tokens=getattr(usage, "output_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
    )


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
