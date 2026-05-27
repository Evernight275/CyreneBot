from __future__ import annotations
from typing import Any, cast

from cyreneAI.core.schema.chat import (
    ChatRequest,
    ChatResponse,
    ChatFinishReason,
)
from cyreneAI.core.schema.embedding import (
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingVector,
)
from cyreneAI.core.schema.usage import TokenUsage
from cyreneAI.core.schema.tool import (
    ToolDefinition,
    ToolCall,
    ToolChoice,
)
from cyreneAI.core.schema.message import (
    MessageRole,
    ContentPartType,
    ContentPart,
    Message,
)

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
    ChatCompletionToolChoiceOptionParam,
)
from openai.types import CreateEmbeddingResponse


def map_chat_request(request: ChatRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [map_message(message) for message in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "stream": request.stream,
        "top_p": request.top_p,
        "frequency_penalty": request.frequency_penalty,
        "presence_penalty": request.presence_penalty,
        "tools": map_tools(request.tools),
        "tool_choice": map_tool_choice(request.tool_choice),
    }
    return _drop_none(payload)


def map_message(message: Message) -> ChatCompletionMessageParam:
    payload: dict[str, Any] = {
        "role": message.role.value,
        "content": map_content_parts(message.content),
        "name": message.name,
        "tool_call_id": message.tool_call_id,
    }
    return cast(ChatCompletionMessageParam, _drop_none(payload))


def map_content_parts(parts: list[ContentPart] | None) -> str | None:
    if not parts:
        return None

    texts = [
        part.text
        for part in parts
        if part.type == ContentPartType.TEXT and part.text is not None
    ]
    if not texts:
        return None

    return "\n".join(texts)


def map_tool(tool: ToolDefinition) -> ChatCompletionToolParam:
    payload: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters_schema
            or {
                "type": "object",
                "properties": {},
            },
        },
    }
    return cast(ChatCompletionToolParam, payload)


def map_tools(
    tools: list[ToolDefinition] | None,
) -> list[ChatCompletionToolParam] | None:
    if not tools:
        return None
    return [map_tool(tool) for tool in tools]


def map_tool_choice(
    tool_choice: ToolChoice | None,
) -> ChatCompletionToolChoiceOptionParam | None:
    if tool_choice is None:
        return None

    if tool_choice.mode in {"auto", "none", "required"}:
        return cast(ChatCompletionToolChoiceOptionParam, tool_choice.mode)

    if tool_choice.mode == "tool" and tool_choice.name:
        payload: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": tool_choice.name,
            },
        }
        return cast(ChatCompletionToolChoiceOptionParam, payload)

    return None


def map_chat_response(provider_id: str, response: ChatCompletion) -> ChatResponse:
    choice = response.choices[0] if response.choices else None
    openai_message = choice.message if choice is not None else None

    message = None
    tool_calls: list[ToolCall] = []

    if openai_message is not None:
        content_text = openai_message.content or openai_message.refusal
        message = Message(
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
        )

        if openai_message.tool_calls:
            tool_calls = [
                tool_call
                for tool_call in (
                    map_tool_call(openai_tool_call)
                    for openai_tool_call in openai_message.tool_calls
                )
                if tool_call is not None
            ]

    return ChatResponse(
        provider_id=provider_id,
        model=response.model,
        message=message,
        tool_calls=tool_calls,
        finish_reason=map_finish_reason(choice.finish_reason if choice else None),
        usage=map_usage(response.usage),
        raw=response.model_dump(mode="json"),
    )


def map_finish_reason(reason: str | None) -> ChatFinishReason:
    if reason == "stop":
        return ChatFinishReason.STOP
    if reason == "length":
        return ChatFinishReason.LENGTH
    if reason in {"tool_calls", "function_call"}:
        return ChatFinishReason.TOOL_CALLS
    if reason == "content_filter":
        return ChatFinishReason.CONTENT_FILTER
    return ChatFinishReason.UNKNOWN


def map_usage(usage: Any | None) -> TokenUsage | None:
    if usage is None:
        return None

    return TokenUsage(
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
    )


def map_tool_call(tool_call: Any) -> ToolCall | None:
    if getattr(tool_call, "type", None) != "function":
        return None

    function = getattr(tool_call, "function", None)
    if function is None:
        return None

    return ToolCall(
        id=getattr(tool_call, "id", ""),
        name=getattr(function, "name", ""),
        arguments=getattr(function, "arguments", None),
    )


def map_embedding_request(request: EmbeddingRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "input": request.input,
        "dimensions": request.dimensions,
    }
    return _drop_none(payload)


def map_embedding_response(
    provider_id: str,
    response: CreateEmbeddingResponse,
) -> EmbeddingResponse:
    embeddings = [
        EmbeddingVector(
            index=getattr(item, "index", index),
            embedding=list(getattr(item, "embedding", [])),
        )
        for index, item in enumerate(response.data)
    ]
    return EmbeddingResponse(
        provider_id=provider_id,
        model=response.model,
        embeddings=embeddings,
        usage=map_usage(response.usage),
        raw=response.model_dump(mode="json"),
    )


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
