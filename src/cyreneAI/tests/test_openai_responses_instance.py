from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from openai.types.responses import Response

from cyreneAI.core.errors.provider import (
    ProviderConfigurationError,
    ProviderError,
    ProviderResponseError,
)
from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest
from cyreneAI.core.schema.image import ImageGenerationRequest
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
        stream_events: list[Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.stream_events = stream_events
        self.error = error
        self.payload: dict[str, Any] | None = None

    async def create(self, **payload: Any) -> Any:
        self.payload = payload
        if self.error is not None:
            raise self.error
        if payload.get("stream") is True:
            return _FakeStream(self.stream_events or [])
        assert self.response is not None
        return self.response


class _FakeStream:
    def __init__(self, events: list[Any]) -> None:
        self._events = events

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for event in self._events:
            yield event


class _FakeModels:
    async def list(self) -> Any:
        return type(
            "ModelList",
            (),
            {"data": [type("Model", (), {"id": "gpt-test"})()]},
        )()


class _FailingModels:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def list(self) -> Any:
        raise self.error


class _FakeImages:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    async def generate(self, **payload: Any) -> Any:
        self.payload = payload
        return SimpleNamespace(
            data=[
                SimpleNamespace(
                    b64_json="aW1hZ2U=",
                    url=None,
                    revised_prompt="A small robot.",
                )
            ],
            model_dump=lambda mode: {"data": [{"b64_json": "aW1hZ2U="}]},
        )


class _FailingImages:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def generate(self, **payload: Any) -> Any:
        raise self.error


class _FakeOpenAIClient:
    def __init__(self, responses: _FakeResponses) -> None:
        self.responses = responses
        self.models = _FakeModels()
        self.images = _FakeImages()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FailingStream:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        raise self.error
        yield


class _BrokenStreamResponses:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.payload: dict[str, Any] | None = None

    async def create(self, **payload: Any) -> Any:
        self.payload = payload
        return _FailingStream(self.error)


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


def test_openai_responses_instance_streams_chat_chunks() -> None:
    async def run() -> None:
        responses = _FakeResponses(
            stream_events=[
                SimpleNamespace(
                    type="response.output_text.delta",
                    delta="Hel",
                    response=SimpleNamespace(model="gpt-test"),
                ),
                SimpleNamespace(
                    type="response.output_text.delta",
                    delta="lo",
                    response=SimpleNamespace(model="gpt-test"),
                ),
                SimpleNamespace(
                    type="response.completed",
                    response=_response(),
                ),
            ],
        )
        instance = OpenAIResponsesProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=_FakeOpenAIClient(responses),
        )

        chunks = [chunk async for chunk in instance.chat_stream(_request())]

        assert responses.payload is not None
        assert responses.payload["stream"] is True
        assert responses.payload["model"] == "gpt-test"
        assert [chunk.delta_text for chunk in chunks[:2]] == ["Hel", "lo"]
        assert chunks[-1].finish_reason == ChatFinishReason.STOP

    asyncio.run(run())


def test_openai_responses_instance_stream_translates_error_event() -> None:
    async def run() -> None:
        instance = OpenAIResponsesProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=_FakeOpenAIClient(
                _FakeResponses(
                    stream_events=[
                        SimpleNamespace(
                            type="error",
                            message="stream failed",
                            code="bad_stream",
                        )
                    ],
                )
            ),
        )

        with pytest.raises(ProviderResponseError) as caught:
            _ = [chunk async for chunk in instance.chat_stream(_request())]

        assert "stream failed" in str(caught.value)

    asyncio.run(run())


def test_openai_responses_instance_stream_translates_create_errors() -> None:
    async def run() -> None:
        error = RuntimeError("stream create failed")
        instance = OpenAIResponsesProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=_FakeOpenAIClient(_FakeResponses(error=error)),
        )

        with pytest.raises(ProviderError) as caught:
            _ = [chunk async for chunk in instance.chat_stream(_request())]

        assert caught.value.cause is error

    asyncio.run(run())


def test_openai_responses_instance_stream_translates_iteration_errors() -> None:
    async def run() -> None:
        error = RuntimeError("stream iteration failed")
        responses = _BrokenStreamResponses(error)
        instance = OpenAIResponsesProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=_FakeOpenAIClient(responses),  # type: ignore[arg-type]
        )

        with pytest.raises(ProviderError) as caught:
            _ = [chunk async for chunk in instance.chat_stream(_request())]

        assert responses.payload is not None
        assert responses.payload["stream"] is True
        assert caught.value.cause is error

    asyncio.run(run())


def test_openai_responses_instance_stream_translates_failed_response_events() -> None:
    async def run() -> None:
        failed_with_error = SimpleNamespace(
            type="response.failed",
            response=SimpleNamespace(
                error=SimpleNamespace(message="response failed", code=None)
            ),
        )
        failed_without_error = SimpleNamespace(
            type="response.failed",
            response=SimpleNamespace(error=None),
        )

        for event, expected in [
            (failed_with_error, "response failed"),
            (failed_without_error, "OpenAI Responses stream failed"),
        ]:
            instance = OpenAIResponsesProviderInstance(
                config=_config(),
                info=_provider_info(),
                client=_FakeOpenAIClient(_FakeResponses(stream_events=[event])),
            )

            with pytest.raises(ProviderResponseError) as caught:
                _ = [chunk async for chunk in instance.chat_stream(_request())]

            assert str(caught.value) == expected

    asyncio.run(run())


def test_openai_responses_instance_stream_error_event_uses_object_fallback_message() -> None:
    async def run() -> None:
        error_event = SimpleNamespace(type="error", message=None, code="bad_stream")
        instance = OpenAIResponsesProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=_FakeOpenAIClient(_FakeResponses(stream_events=[error_event])),
        )

        with pytest.raises(ProviderResponseError) as caught:
            _ = [chunk async for chunk in instance.chat_stream(_request())]

        assert "namespace(" in str(caught.value)
        assert "bad_stream" in str(caught.value)

    asyncio.run(run())


def test_openai_responses_instance_lists_models() -> None:
    async def run() -> None:
        instance = OpenAIResponsesProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=_FakeOpenAIClient(_FakeResponses(response=_response())),
        )

        models = await instance.list_models()

        assert [model.model_id for model in models] == ["gpt-test"]

    asyncio.run(run())


def test_openai_responses_instance_list_models_translates_errors() -> None:
    async def run() -> None:
        error = RuntimeError("models failed")
        client = _FakeOpenAIClient(_FakeResponses(response=_response()))
        client.models = _FailingModels(error)
        instance = OpenAIResponsesProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=client,
        )

        with pytest.raises(ProviderError) as caught:
            await instance.list_models()

        assert caught.value.cause is error

    asyncio.run(run())


def test_openai_responses_instance_generates_images() -> None:
    async def run() -> None:
        client = _FakeOpenAIClient(_FakeResponses(response=_response()))
        instance = OpenAIResponsesProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=client,
        )

        response = await instance.generate_image(
            ImageGenerationRequest(
                provider_id="responses-test",
                model="gpt-image-test",
                prompt="A small robot.",
                count=1,
                size="1024x1024",
                quality="medium",
            )
        )

        assert client.images.payload == {
            "model": "gpt-image-test",
            "prompt": "A small robot.",
            "n": 1,
            "size": "1024x1024",
            "quality": "medium",
            "response_format": "b64_json",
        }
        assert response.provider_id == "responses-test"
        assert response.model == "gpt-image-test"
        assert response.images[0].b64_json == "aW1hZ2U="
        assert response.images[0].revised_prompt == "A small robot."

    asyncio.run(run())


def test_openai_responses_instance_generate_image_translates_errors() -> None:
    async def run() -> None:
        error = RuntimeError("image failed")
        client = _FakeOpenAIClient(_FakeResponses(response=_response()))
        client.images = _FailingImages(error)
        instance = OpenAIResponsesProviderInstance(
            config=_config(),
            info=_provider_info(),
            client=client,
        )

        with pytest.raises(ProviderError) as caught:
            await instance.generate_image(
                ImageGenerationRequest(
                    provider_id="responses-test",
                    model="gpt-image-test",
                    prompt="A small robot.",
                )
            )

        assert caught.value.cause is error

    asyncio.run(run())
