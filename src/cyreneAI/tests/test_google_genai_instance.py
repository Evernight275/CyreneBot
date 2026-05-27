from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from google.genai.types import GenerateContentResponse

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
from cyreneAI.infra.adapters.providers.google_genai.instance import (
    GoogleGenAIProviderInstance,
)


def _provider_info() -> ProviderInfo:
    return ProviderInfo(
        provider_type=ProviderType.GOOGLE,
        name="Google GenAI",
        description="test provider",
        capabilities=[ProviderCapability.CHAT],
    )


def _config(api_key: str | None = "test-key") -> ProviderConfig:
    return ProviderConfig(
        provider_id="google-test",
        provider_type=ProviderType.GOOGLE,
        api_key=api_key,
        timeout=timedelta(seconds=3),
    )


def _request() -> ChatRequest:
    return ChatRequest(
        provider_id="google-test",
        model="gemini-test",
        messages=[
            Message(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT, text="hello")],
            )
        ],
    )


def _response() -> GenerateContentResponse:
    return GenerateContentResponse.model_validate(
        {
            "model_version": "gemini-test",
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"text": "pong"}],
                    },
                    "finish_reason": "STOP",
                }
            ],
        }
    )


class _FakeModels:
    def __init__(
        self,
        response: GenerateContentResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.payload: dict[str, Any] | None = None

    def generate_content(self, **payload: Any) -> GenerateContentResponse:
        self.payload = payload
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _FakeGoogleClient:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_google_genai_instance_requires_api_key() -> None:
    with pytest.raises(ProviderConfigurationError):
        GoogleGenAIProviderInstance(
            config=_config(api_key=None),
            info=_provider_info(),
        )


def test_google_genai_instance_chat_maps_payload_and_response() -> None:
    async def run() -> None:
        models = _FakeModels(response=_response())
        client = _FakeGoogleClient(models)
        instance = GoogleGenAIProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=client,
        )

        response = await instance.chat(_request())

        assert instance.timeout == 3
        assert models.payload is not None
        assert models.payload["model"] == "gemini-test"
        assert models.payload["contents"] == [
            {
                "role": "user",
                "parts": [{"text": "hello"}],
            }
        ]
        assert response.finish_reason == ChatFinishReason.STOP
        assert response.message is not None
        assert response.message.content is not None
        assert response.message.content[0].text == "pong"

        await instance.close()
        assert client.closed is True

    asyncio.run(run())


def test_google_genai_instance_chat_translates_errors() -> None:
    async def run() -> None:
        error = RuntimeError("boom")
        instance = GoogleGenAIProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=_FakeGoogleClient(_FakeModels(error=error)),
        )

        with pytest.raises(ProviderError) as caught:
            await instance.chat(_request())

        assert caught.value.cause is error

    asyncio.run(run())
