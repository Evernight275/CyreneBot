from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from openai.types import CreateEmbeddingResponse
from openai.types.chat import ChatCompletion

from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest
from cyreneAI.core.errors.provider import ProviderConfigurationError
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
from cyreneAI.core.schema.tool import ToolChoice, ToolDefinition
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


class _FakeCompletions:
    def __init__(self, response: ChatCompletion) -> None:
        self.response = response
        self.payload = None

    async def create(self, **payload):
        self.payload = payload
        return self.response


class _FakeChat:
    def __init__(self, response: ChatCompletion) -> None:
        self.completions = _FakeCompletions(response)


class _FakeEmbeddings:
    def __init__(self, response: CreateEmbeddingResponse) -> None:
        self.response = response
        self.payload = None

    async def create(self, **payload):
        self.payload = payload
        return self.response


class _FakeOpenAIClient:
    def __init__(
        self,
        response: ChatCompletion | None = None,
        embedding_response: CreateEmbeddingResponse | None = None,
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
        self.chat = _FakeChat(response)
        self.embeddings = _FakeEmbeddings(embedding_response)
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
                                "arguments": "{\"key\":\"value\"}",
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
    assert response.tool_calls[0].arguments == "{\"key\":\"value\"}"

    await instance.close()
    assert client.closed is True


def test_openai_compatible_instance_passes_tool_call_payload() -> None:
    asyncio.run(_run_chat_with_tool_call())


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
