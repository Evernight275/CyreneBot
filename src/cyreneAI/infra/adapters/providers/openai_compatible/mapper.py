from __future__ import annotations
import re
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


def map_chat_request(
    request: ChatRequest,
    *,
    include_reasoning_content: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": map_messages(
            request.messages,
            include_reasoning_content=include_reasoning_content,
        ),
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


def map_messages(
    messages: list[Message],
    *,
    include_reasoning_content: bool = False,
) -> list[ChatCompletionMessageParam]:
    mapped_messages = [
        map_message(
            message,
            include_reasoning_content=include_reasoning_content,
        )
        for message in messages
    ]
    return [message for message in mapped_messages if message is not None]


def map_message(
    message: Message,
    *,
    include_reasoning_content: bool = False,
) -> ChatCompletionMessageParam | None:
    content = map_content_parts(message.content)
    tool_calls = map_message_tool_calls(message.tool_calls)
    reasoning_content = (
        map_reasoning_content(message) if include_reasoning_content else None
    )
    if (
        message.role == MessageRole.ASSISTANT
        and _is_empty_content(content)
        and not tool_calls
        and _is_empty_content(reasoning_content)
    ):
        return None

    payload: dict[str, Any] = {
        "role": message.role.value,
        "content": content,
        "name": message.name,
        "tool_call_id": message.tool_call_id,
        "tool_calls": tool_calls,
        "reasoning_content": reasoning_content,
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


def map_message_tool_calls(
    tool_calls: list[ToolCall] | None,
) -> list[dict[str, Any]] | None:
    if not tool_calls:
        return None
    return [
        {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.name,
                "arguments": tool_call.arguments or "",
            },
        }
        for tool_call in tool_calls
    ]


def map_reasoning_content(message: Message) -> str | None:
    metadata = message.metadata.get("openai_compatible")
    if not isinstance(metadata, dict):
        return None

    reasoning_content = metadata.get("reasoning_content")
    return reasoning_content if isinstance(reasoning_content, str) else None


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
        content_text = normalize_response_content(
            getattr(openai_message, "content", None)
        ) or normalize_response_content(getattr(openai_message, "refusal", None))
        content_text, extracted_reasoning_content = extract_think_content(content_text)
        if openai_message.tool_calls:
            tool_calls = [
                tool_call
                for tool_call in (
                    map_tool_call(openai_tool_call)
                    for openai_tool_call in openai_message.tool_calls
                )
                if tool_call is not None
            ]

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
            tool_calls=tool_calls or None,
            metadata=map_message_metadata(
                openai_message,
                extracted_reasoning_content=extracted_reasoning_content,
            ),
        )

    usage = response.usage or getattr(choice, "usage", None)
    return ChatResponse(
        provider_id=provider_id,
        model=response.model,
        message=message,
        tool_calls=tool_calls,
        finish_reason=map_finish_reason(choice.finish_reason if choice else None),
        usage=map_usage(usage),
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


def map_message_metadata(
    openai_message: Any,
    *,
    extracted_reasoning_content: str | None = None,
) -> dict[str, Any]:
    reasoning_content = (
        getattr(openai_message, "reasoning_content", None)
        or extracted_reasoning_content
    )
    if reasoning_content is None:
        return {}
    return {
        "openai_compatible": {
            "reasoning_content": reasoning_content,
        }
    }


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


def normalize_response_content(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        text = content.get("text")
        return str(text) if text is not None else None
    if isinstance(content, list):
        texts: list[str] = []
        for part in content:
            text = None
            if isinstance(part, dict):
                text = part.get("text")
            else:
                text = getattr(part, "text", None)
            if text is not None:
                texts.append(str(text))
        return "".join(texts) if texts else None
    return str(content)


def extract_think_content(content: str | None) -> tuple[str | None, str | None]:
    if content is None:
        return None, None

    matches = re.findall(r"<think>(.*?)</think>", content, flags=re.DOTALL)
    if not matches:
        return content, None

    reasoning_content = "\n".join(match.strip() for match in matches)
    visible_content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    visible_content = re.sub(r"</think>\s*$", "", visible_content).strip()
    return visible_content or None, reasoning_content or None


def _is_empty_content(content: str | None) -> bool:
    return content is None or content == ""


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
