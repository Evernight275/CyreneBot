from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from anthropic.types import Message as AnthropicMessage

from cyreneAI.core.errors.provider import ProviderConfigurationError, ProviderError
from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest
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
from cyreneAI.infra.adapters.providers.anthropic.instance import (
    AnthropicProviderInstance,
)


def _provider_info() -> ProviderInfo:
    return ProviderInfo(
        provider_type=ProviderType.ANTHROPIC,
        name="Anthropic",
        description="test provider",
        capabilities=[ProviderCapability.CHAT],
    )


def _config(api_key: str | None = "test-key") -> ProviderConfig:
    return ProviderConfig(
        provider_id="anthropic-test",
        provider_type=ProviderType.ANTHROPIC,
        api_key=api_key,
        base_url="https://example.com",
        timeout=timedelta(seconds=3),
    )


def _request() -> ChatRequest:
    return ChatRequest(
        provider_id="anthropic-test",
        model="claude-test",
        messages=[
            Message(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT, text="hello")],
            )
        ],
    )


def _response() -> AnthropicMessage:
    return AnthropicMessage.model_validate(
        {
            "id": "msg-1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": [{"type": "text", "text": "pong"}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 3,
                "output_tokens": 4,
            },
        }
    )


class _FakeMessages:
    def __init__(
        self,
        response: AnthropicMessage | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.payload: dict[str, Any] | None = None

    async def create(self, **payload: Any) -> AnthropicMessage:
        self.payload = payload
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _FakeModels:
    async def list(self) -> Any:
        return type(
            "ModelList",
            (),
            {
                "data": [
                    type(
                        "Model",
                        (),
                        {"id": "claude-test", "display_name": "Claude Test"},
                    )()
                ]
            },
        )()


class _FakeAnthropicClient:
    def __init__(self, messages: _FakeMessages) -> None:
        self.messages = messages
        self.models = _FakeModels()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_anthropic_instance_requires_api_key() -> None:
    with pytest.raises(ProviderConfigurationError):
        AnthropicProviderInstance(
            config=_config(api_key=None),
            info=_provider_info(),
        )


def test_anthropic_instance_chat_maps_payload_and_response() -> None:
    async def run() -> None:
        messages = _FakeMessages(response=_response())
        client = _FakeAnthropicClient(messages)
        instance = AnthropicProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=client,
        )

        response = await instance.chat(_request())

        assert instance.timeout == 3
        assert messages.payload is not None
        assert messages.payload["model"] == "claude-test"
        assert messages.payload["messages"] == [
            {
                "role": "user",
                "content": "hello",
            }
        ]
        assert response.finish_reason == ChatFinishReason.STOP
        assert response.message is not None
        assert response.message.content is not None
        assert response.message.content[0].text == "pong"

        await instance.close()
        assert client.closed is True

    asyncio.run(run())


def test_anthropic_instance_chat_translates_errors() -> None:
    async def run() -> None:
        error = RuntimeError("boom")
        instance = AnthropicProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=_FakeAnthropicClient(_FakeMessages(error=error)),
        )

        with pytest.raises(ProviderError) as caught:
            await instance.chat(_request())

        assert caught.value.cause is error

    asyncio.run(run())


def test_anthropic_instance_lists_models() -> None:
    async def run() -> None:
        instance = AnthropicProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=_FakeAnthropicClient(_FakeMessages(response=_response())),
        )

        models = await instance.list_models()

        assert models[0].model_id == "claude-test"
        assert models[0].name == "Claude Test"

    asyncio.run(run())
