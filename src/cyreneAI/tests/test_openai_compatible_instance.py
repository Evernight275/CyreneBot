from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from openai.types import CreateEmbeddingResponse
from openai.types.chat import ChatCompletion

from cyreneAI.core.errors.provider import ProviderConfigurationError, ProviderError
from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest
from cyreneAI.core.schema.embedding import EmbeddingRequest
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.provider import (
    ProviderCapability,
    ProviderConfig,
    ProviderInfo,
    ProviderType,
)
from cyreneAI.core.schema.tool import ToolCall, ToolChoice, ToolDefinition
from cyreneAI.infra.adapters.providers.openai_compatible.instance import (
    OpenAICompatibleProviderInstance,
)


def _provider_info() -> ProviderInfo:
    return ProviderInfo(
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        name="OpenAI Compatible",
        description="test provider info",
        capabilities=[ProviderCapability.CHAT],
    )


def _text(value: str) -> list[ContentPart]:
    return [ContentPart(type=ContentPartType.TEXT, text=value)]


class _FakeCompletions:
    def __init__(
        self,
        response: ChatCompletion | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.payload = None

    async def create(self, **payload):
        self.payload = payload
        if self.error is not None:
            raise self.error
        return self.response


class _FakeChat:
    def __init__(
        self,
        response: ChatCompletion | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.completions = _FakeCompletions(response, error=error)


class _FakeEmbeddings:
    def __init__(
        self,
        response: CreateEmbeddingResponse,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.payload = None

    async def create(self, **payload):
        self.payload = payload
        if self.error is not None:
            raise self.error
        return self.response


class _FakeModels:
    def __init__(
        self,
        *,
        data: list[Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.data = data
        self.error = error

    async def list(self):
        if self.error is not None:
            raise self.error
        return type(
            "ModelList",
            (),
            {
                "data": self.data
                or [
                    type(
                        "Model",
                        (),
                        {"id": "chat-model", "owned_by": "provider"},
                    )()
                ]
            },
        )()


class _FakeOpenAIClient:
    def __init__(
        self,
        response: ChatCompletion | None = None,
        chat_error: Exception | None = None,
        embedding_response: CreateEmbeddingResponse | None = None,
        embedding_error: Exception | None = None,
        model_data: list[Any] | None = None,
        model_error: Exception | None = None,
    ) -> None:
        if response is None:
            response = ChatCompletion(
                id="chatcmpl-test",
                object="chat.completion",
                created=1,
                model="test-model",
                choices=[],
            )
        if embedding_response is None:
            embedding_response = CreateEmbeddingResponse(
                object="list",
                model="embed-model",
                data=[],
                usage={
                    "prompt_tokens": 0,
                    "total_tokens": 0,
                },
            )
        self.chat = _FakeChat(response, error=chat_error)
        self.embeddings = _FakeEmbeddings(embedding_response, error=embedding_error)
        self.models = _FakeModels(data=model_data, error=model_error)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_openai_compatible_instance_requires_api_key() -> None:
    config = ProviderConfig(
        provider_id="test",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        api_key=None,
    )

    with pytest.raises(ProviderConfigurationError):
        OpenAICompatibleProviderInstance(
            config=config,
            info=_provider_info(),
        )


def test_openai_compatible_instance_converts_timeout_to_seconds() -> None:
    config = ProviderConfig(
        provider_id="test",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        api_key="test-key",
        timeout=timedelta(seconds=3),
    )

    instance = OpenAICompatibleProviderInstance(
        config=config,
        info=_provider_info(),
    )

    assert instance.timeout == 3
    asyncio.run(instance.close())


async def _run_chat_with_tool_call() -> None:
    completion = ChatCompletion(
        id="chatcmpl-test",
        object="chat.completion",
        created=1,
        model="test-model",
        choices=[
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
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
    )
    client = _FakeOpenAIClient(completion)
    config = ProviderConfig(
        provider_id="test",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        api_key="test-key",
        timeout=timedelta(seconds=3),
    )
    instance = OpenAICompatibleProviderInstance(
        config=config,
        info=_provider_info(),
        client=client,
    )
    request = ChatRequest(
        provider_id="test",
        model="test-model",
        messages=[
            Message(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT, text="lookup it")],
            )
        ],
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

    response = await instance.chat(request)

    assert client.chat.completions.payload is not None
    assert client.chat.completions.payload["tools"] == [
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
    assert client.chat.completions.payload["tool_choice"] == {
        "type": "function",
        "function": {
            "name": "lookup",
        },
    }
    assert response.finish_reason == ChatFinishReason.TOOL_CALLS
    assert response.tool_calls[0].id == "call-1"
    assert response.tool_calls[0].name == "lookup"
    assert response.tool_calls[0].arguments == '{"key":"value"}'

    await instance.close()
    assert client.closed is True


def test_openai_compatible_instance_passes_tool_call_payload() -> None:
    asyncio.run(_run_chat_with_tool_call())


async def _run_chat_omits_reasoning_content_for_standard_provider() -> None:
    client = _FakeOpenAIClient()
    config = ProviderConfig(
        provider_id="standard-openai-compatible",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        api_key="test-key",
    )
    instance = OpenAICompatibleProviderInstance(
        config=config,
        info=_provider_info(),
        client=client,
    )

    await instance.chat(_request_with_reasoning_content())

    assert client.chat.completions.payload is not None
    assert "reasoning_content" not in client.chat.completions.payload["messages"][0]


def test_openai_compatible_instance_omits_reasoning_content_by_default() -> None:
    asyncio.run(_run_chat_omits_reasoning_content_for_standard_provider())


async def _run_chat_includes_reasoning_content_for_deepseek_provider() -> None:
    client = _FakeOpenAIClient()
    config = ProviderConfig(
        provider_id="deepseek",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        api_key="test-key",
    )
    instance = OpenAICompatibleProviderInstance(
        config=config,
        info=_provider_info(),
        client=client,
    )

    await instance.chat(_request_with_reasoning_content())

    assert client.chat.completions.payload is not None
    assert client.chat.completions.payload["messages"][0]["reasoning_content"] == (
        "thinking before tool call"
    )


def test_openai_compatible_instance_includes_reasoning_content_for_deepseek() -> None:
    asyncio.run(_run_chat_includes_reasoning_content_for_deepseek_provider())


def _request_with_reasoning_content() -> ChatRequest:
    return ChatRequest(
        provider_id="test",
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
                metadata={
                    "openai_compatible": {
                        "reasoning_content": "thinking before tool call",
                    }
                },
            )
        ],
    )


async def _run_embedding_request() -> None:
    embedding_response = CreateEmbeddingResponse(
        object="list",
        model="embed-model",
        data=[
            {
                "object": "embedding",
                "index": 0,
                "embedding": [0.1, 0.2],
            }
        ],
        usage={
            "prompt_tokens": 2,
            "total_tokens": 2,
        },
    )
    client = _FakeOpenAIClient(embedding_response=embedding_response)
    config = ProviderConfig(
        provider_id="test",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        api_key="test-key",
    )
    instance = OpenAICompatibleProviderInstance(
        config=config,
        info=_provider_info(),
        client=client,
    )

    response = await instance.embed(
        EmbeddingRequest(
            provider_id="test",
            model="embed-model",
            input=["hello", "world"],
            dimensions=128,
        )
    )

    assert client.embeddings.payload == {
        "model": "embed-model",
        "input": ["hello", "world"],
        "dimensions": 128,
    }
    assert response.provider_id == "test"
    assert response.model == "embed-model"
    assert response.embeddings[0].embedding == [0.1, 0.2]
    assert response.usage is not None
    assert response.usage.prompt_tokens == 2

    await instance.close()
    assert client.closed is True


def test_openai_compatible_instance_passes_embedding_payload() -> None:
    asyncio.run(_run_embedding_request())


def test_openai_compatible_instance_lists_models() -> None:
    async def run() -> None:
        instance = OpenAICompatibleProviderInstance(
            config=ProviderConfig(
                provider_id="test",
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                api_key="test-key",
            ),
            info=_provider_info(),
            client=_FakeOpenAIClient(),
        )

        models = await instance.list_models()

        assert models[0].model_id == "chat-model"
        assert models[0].metadata == {"owned_by": "provider"}

    asyncio.run(run())


def test_openai_compatible_instance_lists_string_models() -> None:
    async def run() -> None:
        instance = OpenAICompatibleProviderInstance(
            config=ProviderConfig(
                provider_id="test",
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                api_key="test-key",
            ),
            info=_provider_info(),
            client=_FakeOpenAIClient(model_data=["chat-model"]),
        )

        models = await instance.list_models()

        assert models[0].model_id == "chat-model"

    asyncio.run(run())


def test_openai_compatible_instance_translates_model_list_errors() -> None:
    async def run() -> None:
        error = AttributeError(
            "'str' object has no attribute '_set_private_attributes'"
        )
        instance = OpenAICompatibleProviderInstance(
            config=ProviderConfig(
                provider_id="test",
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                api_key="test-key",
            ),
            info=_provider_info(),
            client=_FakeOpenAIClient(model_error=error),
        )

        with pytest.raises(ProviderError) as caught:
            await instance.list_models()

        assert caught.value.cause is error

    asyncio.run(run())


def test_openai_compatible_instance_filters_blank_models() -> None:
    async def run() -> None:
        instance = OpenAICompatibleProviderInstance(
            config=ProviderConfig(
                provider_id="test",
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                api_key="test-key",
            ),
            info=_provider_info(),
            client=_FakeOpenAIClient(
                model_data=[
                    "",
                    {"id": ""},
                    {"id": "dict-model", "display_name": "Dict Model"},
                    SimpleNamespace(name="named-model", owned_by="owner"),
                ]
            ),
        )

        models = await instance.list_models()

        assert [model.model_id for model in models] == ["dict-model", "named-model"]
        assert models[0].name == "Dict Model"
        assert models[1].metadata == {"owned_by": "owner"}

    asyncio.run(run())


def test_openai_compatible_instance_translates_chat_and_embedding_errors() -> None:
    async def run() -> None:
        chat_error = RuntimeError("chat failed")
        chat_instance = OpenAICompatibleProviderInstance(
            config=ProviderConfig(
                provider_id="test",
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                api_key="test-key",
            ),
            info=_provider_info(),
            client=_FakeOpenAIClient(chat_error=chat_error),
        )

        with pytest.raises(ProviderError) as chat_caught:
            await chat_instance.chat(
                ChatRequest(
                    provider_id="test",
                    model="test-model",
                    messages=[Message(role=MessageRole.USER, content=_text("hi"))],
                )
            )
        assert chat_caught.value.cause is chat_error

        embedding_error = RuntimeError("embedding failed")
        embedding_instance = OpenAICompatibleProviderInstance(
            config=ProviderConfig(
                provider_id="test",
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                api_key="test-key",
            ),
            info=_provider_info(),
            client=_FakeOpenAIClient(embedding_error=embedding_error),
        )

        with pytest.raises(ProviderError) as embedding_caught:
            await embedding_instance.embed(
                EmbeddingRequest(
                    provider_id="test",
                    model="embed-model",
                    input="hello",
                )
            )
        assert embedding_caught.value.cause is embedding_error

    asyncio.run(run())


class _FakeStream:
    def __init__(
        self,
        chunks: list[Any],
        *,
        error_after_chunks: Exception | None = None,
    ) -> None:
        self._chunks = chunks
        self._error_after_chunks = error_after_chunks

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._chunks:
            return self._chunks.pop(0)
        if self._error_after_chunks is not None:
            error = self._error_after_chunks
            self._error_after_chunks = None
            raise error
        raise StopAsyncIteration


def _stream_chunk(
    *,
    content: str | None = None,
    finish_reason: str | None = None,
    model: str = "test-model",
) -> Any:
    return SimpleNamespace(
        model=model,
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=None),
                finish_reason=finish_reason,
            )
        ],
        usage=None,
    )


def test_openai_compatible_instance_streams_chunks_with_usage_options() -> None:
    async def run() -> None:
        stream = _FakeStream(
            [
                _stream_chunk(content="hello"),
                _stream_chunk(finish_reason="stop"),
            ]
        )
        client = _FakeOpenAIClient(response=stream)
        instance = OpenAICompatibleProviderInstance(
            config=ProviderConfig(
                provider_id="test",
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                api_key="test-key",
            ),
            info=_provider_info(),
            client=client,
        )

        chunks = [
            chunk
            async for chunk in instance.chat_stream(
                ChatRequest(
                    provider_id="test",
                    model="test-model",
                    messages=[Message(role=MessageRole.USER, content=_text("hi"))],
                )
            )
        ]

        assert client.chat.completions.payload is not None
        assert client.chat.completions.payload["stream"] is True
        assert client.chat.completions.payload["stream_options"] == {
            "include_usage": True
        }
        assert chunks[0].delta_text == "hello"
        assert chunks[1].finish_reason == ChatFinishReason.STOP

    asyncio.run(run())


def test_openai_compatible_instance_translates_stream_create_and_iter_errors() -> None:
    async def run() -> None:
        create_error = RuntimeError("stream create failed")
        create_instance = OpenAICompatibleProviderInstance(
            config=ProviderConfig(
                provider_id="test",
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                api_key="test-key",
            ),
            info=_provider_info(),
            client=_FakeOpenAIClient(chat_error=create_error),
        )

        with pytest.raises(ProviderError) as create_caught:
            [
                chunk
                async for chunk in create_instance.chat_stream(
                    ChatRequest(
                        provider_id="test",
                        model="test-model",
                        messages=[Message(role=MessageRole.USER, content=_text("hi"))],
                    )
                )
            ]
        assert create_caught.value.cause is create_error

        iter_error = RuntimeError("stream iter failed")
        iter_instance = OpenAICompatibleProviderInstance(
            config=ProviderConfig(
                provider_id="test",
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                api_key="test-key",
            ),
            info=_provider_info(),
            client=_FakeOpenAIClient(
                response=_FakeStream(
                    [_stream_chunk(content="before error")],
                    error_after_chunks=iter_error,
                )
            ),
        )

        with pytest.raises(ProviderError) as iter_caught:
            [
                chunk
                async for chunk in iter_instance.chat_stream(
                    ChatRequest(
                        provider_id="test",
                        model="test-model",
                        messages=[Message(role=MessageRole.USER, content=_text("hi"))],
                    )
                )
            ]
        assert iter_caught.value.cause is iter_error

    asyncio.run(run())
