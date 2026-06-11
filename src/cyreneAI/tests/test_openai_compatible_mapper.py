from __future__ import annotations

from types import SimpleNamespace

from openai.types import CreateEmbeddingResponse
from openai.types.chat import ChatCompletion

from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest
from cyreneAI.core.schema.embedding import EmbeddingRequest
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.tool import ToolCall, ToolChoice, ToolDefinition
from cyreneAI.infra.adapters.providers.openai_compatible.mapper import (
    map_chat_chunk,
    map_chat_request,
    map_chat_response,
    map_embedding_request,
    map_embedding_response,
    map_finish_reason,
)


def test_map_chat_request_builds_openai_compatible_payload() -> None:
    request = ChatRequest(
        provider_id="provider-1",
        model="test-model",
        messages=[
            Message(
                role=MessageRole.USER,
                content=[
                    ContentPart(type=ContentPartType.TEXT, text="hello"),
                    ContentPart(
                        type=ContentPartType.IMAGE,
                        url="https://example.test/cat.png",
                        detail="low",
                    ),
                ],
            ),
            Message(
                role=MessageRole.ASSISTANT,
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="lookup",
                        arguments='{"key":"value"}',
                    )
                ],
                metadata={
                    "openai_compatible": {
                        "reasoning_content": "thinking before tool call",
                    }
                },
            ),
        ],
        temperature=0,
        max_tokens=16,
        tools=[
            ToolDefinition(
                name="lookup",
                description="Lookup a value.",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                    },
                },
            )
        ],
        tool_choice=ToolChoice(mode="tool", name="lookup"),
    )

    payload = map_chat_request(request)

    assert payload["model"] == "test-model"
    assert payload["messages"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "hello",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "https://example.test/cat.png",
                        "detail": "low",
                    },
                },
            ],
        },
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"key":"value"}',
                    },
                }
            ],
        },
    ]
    deepseek_payload = map_chat_request(
        request,
        include_reasoning_content=True,
    )
    assert deepseek_payload["messages"][1]["reasoning_content"] == (
        "thinking before tool call"
    )
    assert payload["temperature"] == 0
    assert payload["max_tokens"] == 16
    assert payload["stream"] is False
    assert payload["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Lookup a value.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                    },
                },
            },
        }
    ]
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {
            "name": "lookup",
        },
    }
    assert "top_p" not in payload


def test_map_chat_request_filters_empty_assistant_messages() -> None:
    request = ChatRequest(
        provider_id="provider-1",
        model="test-model",
        messages=[
            Message(role=MessageRole.ASSISTANT),
            Message(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT, text="hello")],
            ),
        ],
    )

    payload = map_chat_request(request)

    assert payload["messages"] == [
        {
            "role": "user",
            "content": "hello",
        }
    ]


def test_map_chat_request_uses_generic_reasoning_metadata() -> None:
    request = ChatRequest(
        provider_id="provider-1",
        model="test-model",
        messages=[
            Message(
                role=MessageRole.ASSISTANT,
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="lookup",
                        arguments='{"key":"value"}',
                    )
                ],
                metadata={"reasoning_content": "thinking before tool call"},
            ),
        ],
    )

    payload = map_chat_request(request, include_reasoning_content=True)

    assert payload["messages"][0]["reasoning_content"] == (
        "thinking before tool call"
    )


def test_map_chat_response_builds_core_response() -> None:
    completion = ChatCompletion(
        id="chatcmpl-test",
        object="chat.completion",
        created=1,
        model="test-model",
        choices=[
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "pong",
                    "reasoning_content": "thinking before answer",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "arguments": '{"key":"value"}',
                            },
                        }
                    ],
                },
            }
        ],
        usage={
            "prompt_tokens": 3,
            "completion_tokens": 4,
            "total_tokens": 7,
        },
    )

    response = map_chat_response("provider-1", completion)

    assert response.provider_id == "provider-1"
    assert response.model == "test-model"
    assert response.finish_reason == ChatFinishReason.STOP
    assert response.usage is not None
    assert response.usage.prompt_tokens == 3
    assert response.usage.completion_tokens == 4
    assert response.usage.total_tokens == 7
    assert response.message is not None
    assert response.message.role == MessageRole.ASSISTANT
    assert response.message.content is not None
    assert response.message.content[0].text == "pong"
    assert response.message.tool_calls is not None
    assert response.message.tool_calls[0].id == "call-1"
    assert response.message.metadata == {
        "openai_compatible": {
            "reasoning_content": "thinking before answer",
        }
    }
    assert response.tool_calls[0].id == "call-1"
    assert response.tool_calls[0].name == "lookup"
    assert response.tool_calls[0].arguments == '{"key":"value"}'


def test_map_chat_response_normalizes_content_and_extracts_think_tags() -> None:
    completion = SimpleNamespace(
        model="test-model",
        usage=None,
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                usage=SimpleNamespace(
                    prompt_tokens=5,
                    completion_tokens=6,
                    total_tokens=11,
                ),
                message=SimpleNamespace(
                    content=[
                        {"type": "text", "text": "<think>hidden</think>"},
                        {"type": "text", "text": "visible"},
                    ],
                    refusal=None,
                    tool_calls=None,
                    reasoning_content=None,
                ),
            )
        ],
        model_dump=lambda mode: {"model": "test-model"},
    )

    response = map_chat_response("provider-1", completion)

    assert response.message is not None
    assert response.message.content is not None
    assert response.message.content[0].text == "visible"
    assert response.message.metadata == {
        "openai_compatible": {
            "reasoning_content": "hidden",
        }
    }
    assert response.usage is not None
    assert response.usage.prompt_tokens == 5
    assert response.usage.completion_tokens == 6
    assert response.usage.total_tokens == 11


def test_map_finish_reason_handles_known_and_unknown_values() -> None:
    assert map_finish_reason("stop") == ChatFinishReason.STOP
    assert map_finish_reason("length") == ChatFinishReason.LENGTH
    assert map_finish_reason("tool_calls") == ChatFinishReason.TOOL_CALLS
    assert map_finish_reason("function_call") == ChatFinishReason.TOOL_CALLS
    assert map_finish_reason("content_filter") == ChatFinishReason.CONTENT_FILTER
    assert map_finish_reason("something-new") == ChatFinishReason.UNKNOWN
    assert map_finish_reason(None) == ChatFinishReason.UNKNOWN


def test_map_embedding_request_builds_openai_compatible_payload() -> None:
    request = EmbeddingRequest(
        provider_id="provider-1",
        model="embed-model",
        input=["hello", "world"],
        dimensions=128,
    )

    payload = map_embedding_request(request)

    assert payload == {
        "model": "embed-model",
        "input": ["hello", "world"],
        "dimensions": 128,
    }


def test_map_embedding_response_builds_core_response() -> None:
    response = CreateEmbeddingResponse(
        object="list",
        model="embed-model",
        data=[
            {
                "object": "embedding",
                "index": 0,
                "embedding": [0.1, 0.2],
            },
            {
                "object": "embedding",
                "index": 1,
                "embedding": [0.3, 0.4],
            },
        ],
        usage={
            "prompt_tokens": 3,
            "total_tokens": 3,
        },
    )

    mapped = map_embedding_response("provider-1", response)

    assert mapped.provider_id == "provider-1"
    assert mapped.model == "embed-model"
    assert [item.index for item in mapped.embeddings] == [0, 1]
    assert [item.embedding for item in mapped.embeddings] == [
        [0.1, 0.2],
        [0.3, 0.4],
    ]
    assert mapped.usage is not None
    assert mapped.usage.prompt_tokens == 3
    assert mapped.usage.total_tokens == 3
    assert mapped.raw is not None


def _chunk(delta: object, *, finish_reason: object = None, usage: object = None):
    return SimpleNamespace(
        model="stream-model",
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)],
        usage=usage,
    )


def test_map_chat_chunk_maps_text_delta() -> None:
    chunk = _chunk(SimpleNamespace(content="Hello", reasoning_content=None, tool_calls=None))

    mapped = map_chat_chunk("provider-1", chunk)

    assert mapped.provider_id == "provider-1"
    assert mapped.model == "stream-model"
    assert mapped.delta_text == "Hello"
    assert mapped.reasoning_delta is None
    assert mapped.tool_call_deltas == []
    assert mapped.finish_reason is None


def test_map_chat_chunk_maps_reasoning_delta() -> None:
    chunk = _chunk(
        SimpleNamespace(content=None, reasoning_content="thinking", tool_calls=None)
    )

    mapped = map_chat_chunk("provider-1", chunk)

    assert mapped.delta_text is None
    assert mapped.reasoning_delta == "thinking"


def test_map_chat_chunk_maps_tool_call_deltas() -> None:
    tool_call = SimpleNamespace(
        index=0,
        id="call-1",
        function=SimpleNamespace(name="lookup", arguments='{"k":'),
    )
    chunk = _chunk(
        SimpleNamespace(content=None, reasoning_content=None, tool_calls=[tool_call]),
        finish_reason="tool_calls",
    )

    mapped = map_chat_chunk("provider-1", chunk)

    assert mapped.finish_reason == ChatFinishReason.TOOL_CALLS
    assert len(mapped.tool_call_deltas) == 1
    delta = mapped.tool_call_deltas[0]
    assert delta.index == 0
    assert delta.id == "call-1"
    assert delta.name == "lookup"
    assert delta.arguments == '{"k":'


def test_map_chat_chunk_maps_usage_on_final_chunk() -> None:
    chunk = _chunk(
        SimpleNamespace(content=None, reasoning_content=None, tool_calls=None),
        finish_reason="stop",
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7, total_tokens=12),
    )

    mapped = map_chat_chunk("provider-1", chunk)

    assert mapped.finish_reason == ChatFinishReason.STOP
    assert mapped.usage is not None
    assert mapped.usage.total_tokens == 12
