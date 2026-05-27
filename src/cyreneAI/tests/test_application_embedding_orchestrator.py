from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from cyreneAI.application.embedding_orchestrator import (
    ApplicationEmbeddingRequest,
    EmbeddingOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.errors.base import UnsupportedError
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.embedding import (
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingVector,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType


class FakeEmbeddingProvider:
    info = ProviderInfo(
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        name="fake",
        description="Fake embedding provider.",
    )
    config = ProviderConfig(
        provider_id="provider-1",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        timeout=timedelta(seconds=1),
    )

    def __init__(self) -> None:
        self.requests: list[EmbeddingRequest] = []

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.requests.append(request)
        return EmbeddingResponse(
            provider_id=request.provider_id,
            model=request.model,
            embeddings=[
                EmbeddingVector(index=0, embedding=[0.1, 0.2]),
            ],
        )

    async def close(self) -> None:
        pass


class FakeChatOnlyProvider:
    info = FakeEmbeddingProvider.info
    config = FakeEmbeddingProvider.config

    async def close(self) -> None:
        pass


async def _build_provider_manager(provider) -> ProviderManager:
    factory = ProviderFactory()

    async def build_provider(config: ProviderConfig):
        return provider

    factory.register(ProviderType.OPENAI_COMPATIBLE, build_provider)
    manager = ProviderManager(factory)
    await manager.add(provider.config)
    return manager


def test_embedding_orchestrator_calls_embedding_provider() -> None:
    async def run() -> None:
        provider = FakeEmbeddingProvider()
        runtime = CyreneAIRuntime(
            provider_manager=await _build_provider_manager(provider),
            context_builder=ContextWindowBuilder(),
        )

        result = await EmbeddingOrchestrator(runtime).embed(
            ApplicationEmbeddingRequest(
                provider_id="provider-1",
                model="embed-model",
                input=["hello", "world"],
                dimensions=128,
                metadata={"purpose": "rag"},
            )
        )

        assert provider.requests == [
            EmbeddingRequest(
                provider_id="provider-1",
                model="embed-model",
                input=["hello", "world"],
                dimensions=128,
                metadata={"purpose": "rag"},
            )
        ]
        assert result.response.embeddings[0].embedding == [0.1, 0.2]
        assert result.metadata == {
            "purpose": "rag",
            "embedding_count": 1,
        }

    asyncio.run(run())


def test_embedding_orchestrator_rejects_provider_without_embedding() -> None:
    async def run() -> None:
        runtime = CyreneAIRuntime(
            provider_manager=await _build_provider_manager(FakeChatOnlyProvider()),
            context_builder=ContextWindowBuilder(),
        )

        with pytest.raises(UnsupportedError):
            await EmbeddingOrchestrator(runtime).embed(
                ApplicationEmbeddingRequest(
                    provider_id="provider-1",
                    model="embed-model",
                    input="hello",
                )
            )

    asyncio.run(run())
