from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from cyreneAI.application.generation.image_orchestrator import (
    ApplicationImageGenerationRequest,
    ImageGenerationOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.errors.base import UnsupportedError
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.image import (
    GeneratedImage,
    ImageGenerationRequest,
    ImageGenerationResponse,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType


class FakeImageProvider:
    info = ProviderInfo(
        provider_type=ProviderType.OPENAI_RESPONSES,
        name="fake",
        description="Fake image provider.",
    )
    config = ProviderConfig(
        provider_id="provider-1",
        provider_type=ProviderType.OPENAI_RESPONSES,
        timeout=timedelta(seconds=1),
    )

    def __init__(self) -> None:
        self.requests: list[ImageGenerationRequest] = []

    async def generate_image(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResponse:
        self.requests.append(request)
        return ImageGenerationResponse(
            provider_id=request.provider_id,
            model=request.model,
            images=[
                GeneratedImage(
                    index=0,
                    b64_json="aW1hZ2U=",
                    mime_type="image/png",
                )
            ],
        )

    async def close(self) -> None:
        pass


class FakeChatOnlyProvider:
    info = FakeImageProvider.info
    config = FakeImageProvider.config

    async def close(self) -> None:
        pass


async def _build_provider_manager(provider) -> ProviderManager:
    factory = ProviderFactory()

    async def build_provider(config: ProviderConfig):
        return provider

    factory.register(ProviderType.OPENAI_RESPONSES, build_provider)
    manager = ProviderManager(factory)
    await manager.add(provider.config)
    return manager


def test_image_orchestrator_calls_provider() -> None:
    async def run() -> None:
        provider = FakeImageProvider()
        runtime = CyreneAIRuntime(
            provider_manager=await _build_provider_manager(provider),
            context_builder=ContextWindowBuilder(),
        )

        result = await ImageGenerationOrchestrator(runtime).generate_image(
            ApplicationImageGenerationRequest(
                provider_id="provider-1",
                model="image-model",
                prompt="A small robot.",
                size="1024x1024",
                metadata={"purpose": "test"},
            )
        )

        assert provider.requests[0].model == "image-model"
        assert provider.requests[0].prompt == "A small robot."
        assert provider.requests[0].size == "1024x1024"
        assert result.response.images[0].b64_json == "aW1hZ2U="
        assert result.metadata == {
            "purpose": "test",
            "image_count": 1,
        }

    asyncio.run(run())


def test_image_orchestrator_rejects_provider_without_image_generation() -> None:
    async def run() -> None:
        runtime = CyreneAIRuntime(
            provider_manager=await _build_provider_manager(FakeChatOnlyProvider()),
            context_builder=ContextWindowBuilder(),
        )

        with pytest.raises(UnsupportedError):
            await ImageGenerationOrchestrator(runtime).generate_image(
                ApplicationImageGenerationRequest(
                    provider_id="provider-1",
                    model="image-model",
                    prompt="A small robot.",
                )
            )

    asyncio.run(run())
