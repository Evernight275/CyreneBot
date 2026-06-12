from __future__ import annotations

import base64
import json
from typing import Any, cast

from cyreneAI.core.schema.chat import (
    ChatFinishReason,
    ChatRequest,
    ChatResponse,
    ChatStreamChunk,
    ToolCallDelta,
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

    if message.role == MessageRole.ASSISTANT and message.tool_calls:
        return [
            *map_text_parts(message.content),
            *map_function_call_parts(message.tool_calls),
        ]

    return map_content_part_blocks(message.content)


def map_content_parts(parts: list[ContentPart] | None) -> str:
    if not parts:
        return ""
    texts = [
        part.text
        for part in parts
        if part.type == ContentPartType.TEXT and part.text is not None
    ]
    return "\n".join(texts)


def map_text_parts(parts: list[ContentPart] | None) -> list[dict[str, Any]]:
    text = map_content_parts(parts)
    return [{"text": text}] if text else []


def map_content_part_blocks(parts: list[ContentPart] | None) -> list[dict[str, Any]]:
    if not parts:
        return []

    if not has_mappable_image(parts):
        return map_text_parts(parts)

    blocks: list[dict[str, Any]] = []
    for part in parts:
        if part.type == ContentPartType.TEXT and part.text is not None:
            blocks.append({"text": part.text})
            continue

        if part.type == ContentPartType.IMAGE:
            image_part = map_image_part(part)
            if image_part is not None:
                blocks.append(image_part)

    return blocks


def map_image_part(part: ContentPart) -> dict[str, Any] | None:
    if part.data:
        return {
            "inline_data": {
                "mime_type": part.mime_type or "image/png",
                "data": part.data,
            }
        }
    if part.url:
        return {
            "file_data": _drop_none(
                {
                    "mime_type": part.mime_type,
                    "file_uri": part.url,
                }
            )
        }
    return None


def has_mappable_image(parts: list[ContentPart]) -> bool:
    return any(
        part.type == ContentPartType.IMAGE and bool(part.url or part.data)
        for part in parts
    )


def map_function_call_parts(tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
    return [
        {
            "function_call": {
                "id": tool_call.id,
                "name": tool_call.name,
                "args": map_tool_arguments_object(tool_call.arguments),
            }
        }
        for tool_call in tool_calls
    ]


def map_tool_arguments_object(arguments: str | None) -> Any:
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
        config["function_calling_config"]["allowed_function_names"] = [tool_choice.name]
    return config


def map_google_genai_response(provider_id: str, response: Any) -> ChatResponse:
    candidates = cast(list[Any], getattr(response, "candidates", None) or [])
    candidate = candidates[0] if candidates else None
    parts: list[Any] = []
    if candidate is not None and getattr(candidate, "content", None) is not None:
        parts = cast(list[Any], getattr(candidate.content, "parts", None) or [])

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
        finish_reason=map_finish_reason(candidate, tool_calls),
        usage=map_usage(getattr(response, "usage_metadata", None)),
        raw=(
            response.model_dump(mode="json")
            if hasattr(response, "model_dump")
            else None
        ),
    )


def map_google_genai_stream_chunk(
    provider_id: str,
    chunk: Any,
) -> ChatStreamChunk:
    candidates = cast(list[Any], getattr(chunk, "candidates", None) or [])
    candidate = candidates[0] if candidates else None
    parts: list[Any] = []
    if candidate is not None and getattr(candidate, "content", None) is not None:
        parts = cast(list[Any], getattr(candidate.content, "parts", None) or [])

    tool_call_deltas = [
        delta
        for delta in (
            map_stream_tool_call_delta(part, index) for index, part in enumerate(parts)
        )
        if delta is not None
    ]
    raw_finish_reason = (
        getattr(candidate, "finish_reason", None) if candidate is not None else None
    )
    return ChatStreamChunk(
        provider_id=provider_id,
        model=getattr(chunk, "model_version", None),
        delta_text=map_response_text(
            [part for part in parts if not _is_thought_part(part)]
        ),
        reasoning_delta=map_response_text(
            [part for part in parts if _is_thought_part(part)]
        ),
        tool_call_deltas=tool_call_deltas,
        finish_reason=(
            map_finish_reason(candidate, _tool_calls_from_deltas(tool_call_deltas))
            if candidate is not None and raw_finish_reason is not None
            else None
        ),
        usage=map_usage(getattr(chunk, "usage_metadata", None)),
    )


def map_stream_tool_call_delta(part: Any, index: int) -> ToolCallDelta | None:
    function_call = getattr(part, "function_call", None)
    if function_call is None:
        return None
    return ToolCallDelta(
        index=index,
        id=getattr(function_call, "id", None)
        or getattr(function_call, "name", None)
        or None,
        name=getattr(function_call, "name", None),
        arguments=map_tool_arguments(
            getattr(function_call, "args", None)
            or getattr(function_call, "partial_args", None)
        ),
    )


def map_response_text(parts: list[Any]) -> str | None:
    texts: list[str] = []
    for part in parts:
        text = getattr(part, "text", None)
        if isinstance(text, str) and text:
            texts.append(text)
    if not texts:
        return None
    return "\n".join(texts)


def _is_thought_part(part: Any) -> bool:
    return getattr(part, "thought", None) is True


def _tool_calls_from_deltas(deltas: list[ToolCallDelta]) -> list[ToolCall]:
    return [
        ToolCall(
            id=delta.id or f"call-{delta.index}",
            name=delta.name or "",
            arguments=delta.arguments,
        )
        for delta in deltas
    ]


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


def map_finish_reason(
    candidate: Any | None, tool_calls: list[ToolCall]
) -> ChatFinishReason:
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


def map_google_image_generation_request(
    request: ImageGenerationRequest,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "number_of_images": request.count,
        "aspect_ratio": _map_aspect_ratio(request),
        "image_size": _map_image_size(request),
        "output_mime_type": request.metadata.get("mime_type"),
    }
    return {
        "model": request.model,
        "prompt": request.prompt,
        "config": _drop_none(config),
    }


def should_use_google_generate_images(request: ImageGenerationRequest) -> bool:
    api_type = request.metadata.get("google_api_type") or request.metadata.get(
        "api_type"
    )
    if isinstance(api_type, str):
        normalized_api_type = api_type.strip().lower()
        if normalized_api_type in {"generate_images", "imagen"}:
            return True
        if normalized_api_type in {"generate_content", "gemini"}:
            return False

    return request.model.strip().lower().startswith("imagen")


def map_google_content_image_generation_request(
    request: ImageGenerationRequest,
) -> dict[str, Any]:
    image_config: dict[str, Any] = {
        "aspect_ratio": _map_aspect_ratio(request),
        "image_size": _map_image_size(request),
        "output_mime_type": request.metadata.get("mime_type"),
    }
    config: dict[str, Any] = {
        "response_modalities": _map_response_modalities(request),
        "image_config": _drop_none(image_config),
    }
    return {
        "model": request.model,
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": request.prompt,
                    }
                ],
            }
        ],
        "config": _drop_none(config),
    }


def _map_response_modalities(request: ImageGenerationRequest) -> list[str]:
    raw_modalities = request.metadata.get("response_modalities")
    if isinstance(raw_modalities, list):
        modalities = [
            str(item).upper() for item in cast(list[Any], raw_modalities) if item
        ]
        if modalities:
            return modalities
    return ["IMAGE"]


def _map_aspect_ratio(request: ImageGenerationRequest) -> str | None:
    aspect_ratio = request.metadata.get("aspect_ratio")
    if isinstance(aspect_ratio, str):
        return aspect_ratio
    if request.size and ":" in request.size:
        return request.size
    return None


def _map_image_size(request: ImageGenerationRequest) -> str | None:
    image_size = request.metadata.get("image_size")
    if isinstance(image_size, str):
        return image_size
    if request.size and ":" not in request.size:
        return request.size
    return None


def map_google_image_generation_response(
    provider_id: str,
    model: str,
    response: Any,
) -> ImageGenerationResponse:
    generated_images = cast(
        list[Any], getattr(response, "generated_images", None) or []
    )
    return ImageGenerationResponse(
        provider_id=provider_id,
        model=model,
        images=[
            image
            for image in (
                map_google_generated_image(item, index)
                for index, item in enumerate(generated_images)
            )
            if image is not None
        ],
        raw=(
            response.model_dump(mode="json")
            if hasattr(response, "model_dump")
            else None
        ),
    )


def map_google_content_image_generation_response(
    provider_id: str,
    model: str,
    response: Any,
) -> ImageGenerationResponse:
    candidates = cast(list[Any], getattr(response, "candidates", None) or [])
    candidate = candidates[0] if candidates else None
    parts: list[Any] = []
    if candidate is not None and getattr(candidate, "content", None) is not None:
        parts = cast(list[Any], getattr(candidate.content, "parts", None) or [])

    text_parts = [
        text
        for text in (getattr(part, "text", None) for part in parts)
        if isinstance(text, str) and text
    ]
    images = [
        image
        for image in (
            map_google_content_generated_image(part, index)
            for index, part in enumerate(parts)
        )
        if image is not None
    ]
    revised_prompt = "\n".join(text_parts) or None
    if revised_prompt:
        images = [
            image.model_copy(
                update={"revised_prompt": image.revised_prompt or revised_prompt}
            )
            for image in images
        ]

    return ImageGenerationResponse(
        provider_id=provider_id,
        model=model,
        images=images,
        raw=(
            response.model_dump(mode="json")
            if hasattr(response, "model_dump")
            else None
        ),
    )


def map_google_content_generated_image(part: Any, index: int) -> GeneratedImage | None:
    inline_data = getattr(part, "inline_data", None)
    if inline_data is None:
        return None

    data = getattr(inline_data, "data", None)
    if isinstance(data, bytes):
        b64_json = base64.b64encode(data).decode("ascii")
    elif isinstance(data, str):
        b64_json = data
    else:
        b64_json = None
    if b64_json is None:
        return None

    return GeneratedImage(
        index=index,
        b64_json=b64_json,
        mime_type=getattr(inline_data, "mime_type", None),
    )


def map_google_generated_image(item: Any, index: int) -> GeneratedImage | None:
    image = getattr(item, "image", None)
    if image is None:
        return None

    image_bytes = getattr(image, "image_bytes", None)
    b64_json = (
        base64.b64encode(image_bytes).decode("ascii")
        if isinstance(image_bytes, bytes)
        else None
    )
    return GeneratedImage(
        index=index,
        url=getattr(image, "gcs_uri", None),
        b64_json=b64_json,
        mime_type=getattr(image, "mime_type", None),
        revised_prompt=getattr(item, "enhanced_prompt", None),
        metadata=_drop_none(
            {
                "rai_filtered_reason": getattr(item, "rai_filtered_reason", None),
            }
        ),
    )
