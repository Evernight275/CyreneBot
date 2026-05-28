from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from cyreneAI.application.knowledge.retrieval_orchestrator import (
    ApplicationRetrievalRequest,
    RetrievalOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.errors.base import StateError, UnsupportedError
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.embedding import (
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingVector,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType
from cyreneAI.core.schema.vector import VectorRecord
from cyreneAI.core.vector.manager import VectorManager
from cyreneAI.infra.adapters.vector_stores.memory.store import InMemoryVectorStore


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

    def __init__(self, *, empty: bool = False) -> None:
        self.empty = empty
        self.requests: list[EmbeddingRequest] = []

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.requests.append(request)
        embeddings = [] if self.empty else [EmbeddingVector(index=0, embedding=[1.0, 0.0])]
        return EmbeddingResponse(
            provider_id=request.provider_id,
            model=request.model,
            embeddings=embeddings,
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


async def _build_runtime(
    provider,
    *,
    with_vector_store: bool = True,
) -> CyreneAIRuntime:
    runtime = CyreneAIRuntime(
        provider_manager=await _build_provider_manager(provider),
        context_builder=ContextWindowBuilder(),
    )
    if with_vector_store:
        store = InMemoryVectorStore()
        await store.upsert(
            [
                VectorRecord(
                    record_id="record-1",
                    vector=[1.0, 0.0],
                    content="alpha",
                    metadata={
                        "source": "unit",
                        "kind": "keep",
                        "collection_id": "collection-1",
                    },
                ),
                VectorRecord(
                    record_id="record-2",
                    vector=[0.0, 1.0],
                    content="beta",
                    metadata={
                        "source": "unit",
                        "kind": "drop",
                        "collection_id": "collection-2",
                    },
                ),
            ]
        )
        runtime.vector_manager = VectorManager(store)
    return runtime


def test_retrieval_orchestrator_embeds_query_and_searches_vectors() -> None:
    async def run() -> None:
        provider = FakeEmbeddingProvider()
        runtime = await _build_runtime(provider)

        result = await RetrievalOrchestrator(runtime).retrieve(
            ApplicationRetrievalRequest(
                provider_id="provider-1",
                model="embed-model",
                query="find alpha",
                dimensions=2,
                top_k=1,
                filters={"kind": "keep"},
                collection_id="collection-1",
                metadata={"purpose": "rag"},
            )
        )

        assert provider.requests == [
            EmbeddingRequest(
                provider_id="provider-1",
                model="embed-model",
                input="find alpha",
                dimensions=2,
                metadata={
                    "purpose": "rag",
                    "collection_id": "collection-1",
                },
            )
        ]
        assert [match.record.record_id for match in result.search_result.matches] == [
            "record-1"
        ]
        assert result.metadata == {
            "purpose": "rag",
            "collection_id": "collection-1",
            "match_count": 1,
        }

    asyncio.run(run())


def test_retrieval_orchestrator_rejects_conflicting_collection_filter() -> None:
    async def run() -> None:
        runtime = await _build_runtime(FakeEmbeddingProvider())

        with pytest.raises(ValueError):
            await RetrievalOrchestrator(runtime).retrieve(
                ApplicationRetrievalRequest(
                    provider_id="provider-1",
                    model="embed-model",
                    query="find alpha",
                    filters={"collection_id": "collection-2"},
                    collection_id="collection-1",
                )
            )

    asyncio.run(run())


def test_retrieval_orchestrator_requires_embedding_provider() -> None:
    async def run() -> None:
        runtime = await _build_runtime(FakeChatOnlyProvider())

        with pytest.raises(UnsupportedError):
            await RetrievalOrchestrator(runtime).retrieve(
                ApplicationRetrievalRequest(
                    provider_id="provider-1",
                    model="embed-model",
                    query="hello",
                )
            )

    asyncio.run(run())


def test_retrieval_orchestrator_requires_vector_manager() -> None:
    async def run() -> None:
        runtime = await _build_runtime(
            FakeEmbeddingProvider(),
            with_vector_store=False,
        )

        with pytest.raises(StateError):
            await RetrievalOrchestrator(runtime).retrieve(
                ApplicationRetrievalRequest(
                    provider_id="provider-1",
                    model="embed-model",
                    query="hello",
                )
            )

    asyncio.run(run())


def test_retrieval_orchestrator_rejects_empty_embedding_response() -> None:
    async def run() -> None:
        runtime = await _build_runtime(FakeEmbeddingProvider(empty=True))

        with pytest.raises(StateError):
            await RetrievalOrchestrator(runtime).retrieve(
                ApplicationRetrievalRequest(
                    provider_id="provider-1",
                    model="embed-model",
                    query="hello",
                )
            )

    asyncio.run(run())
