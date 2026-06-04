from __future__ import annotations

from typing import Any, cast

from cyreneAI.core.schema.chat import (
    ChatFinishReason,
    ChatRequest,
    ChatResponse,
)
from cyreneAI.core.schema.image import (
    GeneratedImage,
    ImageGenerationRequest,
    ImageGenerationResponse,
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
    input_items = [
        item for message in request.messages for item in map_input_message(message)
    ]
    payload: dict[str, Any] = {
        "model": request.model,
        "input": drop_unanswered_function_calls(input_items),
        "temperature": request.temperature,
        "max_output_tokens": request.max_tokens,
        "top_p": request.top_p,
        "tools": map_tools(request.tools),
        "tool_choice": map_tool_choice(request.tool_choice),
    }
    return _drop_none(payload)


def map_input_message(message: Message) -> list[dict[str, Any]]:
    if message.role == MessageRole.TOOL:
        return [
            {
                "type": "function_call_output",
                "call_id": message.tool_call_id or "",
                "output": map_content_parts(message.content),
            }
        ]

    items: list[dict[str, Any]] = []
    content = map_content_parts(message.content)
    if content or message.role != MessageRole.ASSISTANT or not message.tool_calls:
        items.append(
            _drop_none(
                {
                    "role": map_message_role(message.role),
                    "content": content,
                }
            )
        )
    if message.role == MessageRole.ASSISTANT:
        items.extend(map_input_tool_calls(message.tool_calls))
    return items


def map_message_role(role: MessageRole) -> str:
    if role == MessageRole.TOOL:
        return "user"
    return role.value


def map_input_tool_calls(tool_calls: list[ToolCall] | None) -> list[dict[str, Any]]:
    if not tool_calls:
        return []
    return [
        {
            "type": "function_call",
            "call_id": tool_call.id,
            "name": tool_call.name,
            "arguments": tool_call.arguments or "",
        }
        for tool_call in tool_calls
    ]


def drop_unanswered_function_calls(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output_call_ids = {
        call_id
        for item in items
        if item.get("type") == "function_call_output"
        for call_id in [item.get("call_id")]
        if isinstance(call_id, str) and call_id
    }
    return [
        item
        for item in items
        if item.get("type") != "function_call" or item.get("call_id") in output_call_ids
    ]


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
    output = cast(list[Any], getattr(response, "output", None) or [])
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
                content=(
                    [
                        ContentPart(
                            type=ContentPartType.TEXT,
                            text=content_text,
                        )
                    ]
                    if content_text
                    else None
                ),
                tool_calls=tool_calls or None,
            )
            if content_text or tool_calls
            else None
        ),
        tool_calls=tool_calls,
        finish_reason=map_finish_reason(response, tool_calls),
        usage=map_usage(getattr(response, "usage", None)),
        raw=(
            response.model_dump(mode="json")
            if hasattr(response, "model_dump")
            else None
        ),
    )


def map_output_text(output: list[Any]) -> str | None:
    texts: list[str] = []
    for item in output:
        if getattr(item, "type", None) != "message":
            continue

        for content in cast(list[Any], getattr(item, "content", None) or []):
            text = getattr(content, "text", None)
            if isinstance(text, str) and text:
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


def map_image_generation_request(request: ImageGenerationRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "prompt": request.prompt,
        "n": request.count,
        "size": request.size,
        "quality": request.quality,
        "response_format": request.response_format,
    }
    return _drop_none(payload)


def map_image_generation_response(
    provider_id: str,
    model: str,
    response: Any,
) -> ImageGenerationResponse:
    data = cast(list[Any], getattr(response, "data", None) or [])
    return ImageGenerationResponse(
        provider_id=provider_id,
        model=model,
        images=[
            GeneratedImage(
                index=index,
                url=getattr(item, "url", None),
                b64_json=getattr(item, "b64_json", None),
                revised_prompt=getattr(item, "revised_prompt", None),
            )
            for index, item in enumerate(data)
        ],
        raw=(
            response.model_dump(mode="json")
            if hasattr(response, "model_dump")
            else None
        ),
    )
