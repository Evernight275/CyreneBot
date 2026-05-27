from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from openai.types.responses import Response

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
from cyreneAI.infra.adapters.providers.openai_responses.instance import (
    OpenAIResponsesProviderInstance,
)


def _provider_info() -> ProviderInfo:
    return ProviderInfo(
        provider_type=ProviderType.OPENAI_RESPONSES,
        name="OpenAI Responses",
        description="test provider",
        capabilities=[ProviderCapability.CHAT],
    )


def _config(api_key: str | None = "test-key") -> ProviderConfig:
    return ProviderConfig(
        provider_id="responses-test",
        provider_type=ProviderType.OPENAI_RESPONSES,
        api_key=api_key,
        base_url="https://example.com",
        timeout=timedelta(seconds=3),
    )


def _request() -> ChatRequest:
    return ChatRequest(
        provider_id="responses-test",
        model="gpt-test",
        messages=[
            Message(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT, text="hello")],
            )
        ],
    )


def _response() -> Response:
    return Response(
        id="resp-test",
        created_at=1,
        model="gpt-test",
        object="response",
        output=[
            {
                "id": "msg-1",
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "pong",
                        "annotations": [],
                    }
                ],
                "status": "completed",
            }
        ],
        parallel_tool_calls=True,
        tool_choice="auto",
        tools=[],
        status="completed",
    )


class _FakeResponses:
    def __init__(
        self,
        response: Response | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.payload: dict[str, Any] | None = None

    async def create(self, **payload: Any) -> Response:
        self.payload = payload
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _FakeOpenAIClient:
    def __init__(self, responses: _FakeResponses) -> None:
        self.responses = responses
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_openai_responses_instance_requires_api_key() -> None:
    with pytest.raises(ProviderConfigurationError):
        OpenAIResponsesProviderInstance(
            config=_config(api_key=None),
            info=_provider_info(),
        )


def test_openai_responses_instance_chat_maps_payload_and_response() -> None:
    async def run() -> None:
        responses = _FakeResponses(response=_response())
        client = _FakeOpenAIClient(responses)
        instance = OpenAIResponsesProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=client,
        )

        response = await instance.chat(_request())

        assert instance.timeout == 3
        assert responses.payload is not None
        assert responses.payload["model"] == "gpt-test"
        assert responses.payload["input"] == [
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


def test_openai_responses_instance_chat_translates_errors() -> None:
    async def run() -> None:
        error = RuntimeError("boom")
        instance = OpenAIResponsesProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=_FakeOpenAIClient(_FakeResponses(error=error)),
        )

        with pytest.raises(ProviderError) as caught:
            await instance.chat(_request())

        assert caught.value.cause is error

    asyncio.run(run())
