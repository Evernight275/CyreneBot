from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from pydantic import ValidationError

from cyreneAI.application.indexing_orchestrator import (
    ApplicationIndexingRequest,
    ChunkStrategy,
    IndexingOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.errors.base import StateError, UnsupportedError
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.document import Document
from cyreneAI.core.schema.embedding import (
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingVector,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType
from cyreneAI.core.schema.vector import VectorQuery
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

    def __init__(self, *, drop_last: bool = False) -> None:
        self.drop_last = drop_last
        self.requests: list[EmbeddingRequest] = []

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.requests.append(request)
        inputs = request.input if isinstance(request.input, list) else [request.input]
        embeddings = [
            EmbeddingVector(
                index=index,
                embedding=[float(index + 1), 0.0],
            )
            for index, _ in enumerate(inputs)
        ]
        if self.drop_last:
            embeddings = embeddings[:-1]
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
        runtime.vector_manager = VectorManager(InMemoryVectorStore())
    return runtime


def test_indexing_orchestrator_chunks_embeds_and_upserts_vectors() -> None:
    async def run() -> None:
        provider = FakeEmbeddingProvider()
        runtime = await _build_runtime(provider)
        orchestrator = IndexingOrchestrator(runtime)

        result = await orchestrator.index(
            ApplicationIndexingRequest(
                provider_id="provider-1",
                model="embed-model",
                documents=[
                    Document(
                        document_id="doc-1",
                        content="abcdefgh",
                        metadata={"source": "unit"},
                    )
                ],
                chunk_size=4,
                chunk_overlap=1,
                dimensions=2,
                collection_id="collection-1",
                metadata={"purpose": "rag"},
            )
        )

        assert [chunk.content for chunk in result.chunks] == [
            "abcd",
            "defg",
            "gh",
        ]
        assert provider.requests == [
            EmbeddingRequest(
                provider_id="provider-1",
                model="embed-model",
                input=["abcd", "defg", "gh"],
                dimensions=2,
                metadata={
                    "purpose": "rag",
                    "collection_id": "collection-1",
                    "chunk_strategy": ChunkStrategy.CHARACTER,
                    "chunk_count": 3,
                },
            )
        ]
        assert [record.record_id for record in result.records] == [
            "doc-1:chunk:0",
            "doc-1:chunk:1",
            "doc-1:chunk:2",
        ]
        assert result.records[0].metadata["document_id"] == "doc-1"
        assert result.records[0].metadata["chunk_id"] == "doc-1:chunk:0"
        assert result.records[0].metadata["chunk_strategy"] == ChunkStrategy.CHARACTER
        assert result.records[0].metadata["collection_id"] == "collection-1"
        assert result.records[0].metadata["source"] == "unit"
        assert result.records[0].metadata["embedding_provider_id"] == "provider-1"
        assert result.records[0].metadata["embedding_model"] == "embed-model"
        assert result.metadata == {
            "purpose": "rag",
            "collection_id": "collection-1",
            "chunk_strategy": ChunkStrategy.CHARACTER,
            "document_count": 1,
            "chunk_count": 3,
            "record_count": 3,
        }

        assert runtime.vector_manager is not None
        search = await runtime.vector_manager.search(
            VectorQuery(
                vector=[1.0, 0.0],
                filters={"collection_id": "collection-1"},
            )
        )
        assert search.matches[0].record.record_id == "doc-1:chunk:0"

    asyncio.run(run())


def test_indexing_orchestrator_chunks_documents_by_paragraph() -> None:
    async def run() -> None:
        provider = FakeEmbeddingProvider()
        runtime = await _build_runtime(provider)
        orchestrator = IndexingOrchestrator(runtime)

        result = await orchestrator.index(
            ApplicationIndexingRequest(
                provider_id="provider-1",
                model="embed-model",
                documents=[
                    Document(
                        document_id="doc-1",
                        content="First paragraph.\n\nSecond paragraph.\n\nThird.",
                    )
                ],
                chunk_size=36,
                chunk_strategy=ChunkStrategy.PARAGRAPH,
            )
        )

        assert [chunk.content for chunk in result.chunks] == [
            "First paragraph.\n\nSecond paragraph.",
            "Third.",
        ]
        assert result.chunks[0].metadata["chunk_strategy"] == ChunkStrategy.PARAGRAPH
        assert result.chunks[0].metadata["start"] == 0
        assert result.chunks[0].metadata["end"] == 35
        assert result.chunks[1].metadata["start"] == 37
        assert result.chunks[1].metadata["end"] == 43
        assert provider.requests[0].metadata["chunk_strategy"] == ChunkStrategy.PARAGRAPH
        assert result.metadata["chunk_strategy"] == ChunkStrategy.PARAGRAPH

    asyncio.run(run())


def test_indexing_orchestrator_splits_oversized_paragraphs_by_character() -> None:
    async def run() -> None:
        provider = FakeEmbeddingProvider()
        runtime = await _build_runtime(provider)
        orchestrator = IndexingOrchestrator(runtime)

        result = await orchestrator.index(
            ApplicationIndexingRequest(
                provider_id="provider-1",
                model="embed-model",
                documents=[
                    Document(
                        document_id="doc-1",
                        content="short\n\nabcdefghijkl",
                    )
                ],
                chunk_size=5,
                chunk_overlap=1,
                chunk_strategy=ChunkStrategy.PARAGRAPH,
            )
        )

        assert [chunk.content for chunk in result.chunks] == [
            "short",
            "abcde",
            "efghi",
            "ijkl",
        ]
        assert [chunk.index for chunk in result.chunks] == [0, 1, 2, 3]
        assert result.chunks[1].metadata["start"] == 7
        assert result.chunks[2].metadata["start"] == 11
        assert result.chunks[3].metadata["start"] == 15

    asyncio.run(run())


def test_indexing_orchestrator_requires_embedding_provider() -> None:
    async def run() -> None:
        runtime = await _build_runtime(FakeChatOnlyProvider())

        with pytest.raises(UnsupportedError):
            await IndexingOrchestrator(runtime).index(
                ApplicationIndexingRequest(
                    provider_id="provider-1",
                    model="embed-model",
                    documents=[Document(document_id="doc-1", content="hello")],
                )
            )

    asyncio.run(run())


def test_indexing_orchestrator_requires_vector_manager() -> None:
    async def run() -> None:
        runtime = await _build_runtime(
            FakeEmbeddingProvider(),
            with_vector_store=False,
        )

        with pytest.raises(StateError):
            await IndexingOrchestrator(runtime).index(
                ApplicationIndexingRequest(
                    provider_id="provider-1",
                    model="embed-model",
                    documents=[Document(document_id="doc-1", content="hello")],
                )
            )

    asyncio.run(run())


def test_indexing_orchestrator_rejects_embedding_count_mismatch() -> None:
    async def run() -> None:
        runtime = await _build_runtime(FakeEmbeddingProvider(drop_last=True))

        with pytest.raises(StateError):
            await IndexingOrchestrator(runtime).index(
                ApplicationIndexingRequest(
                    provider_id="provider-1",
                    model="embed-model",
                    documents=[Document(document_id="doc-1", content="abcdefgh")],
                    chunk_size=4,
                )
            )

    asyncio.run(run())


def test_indexing_request_rejects_overlap_larger_than_chunk_size() -> None:
    with pytest.raises(ValidationError):
        ApplicationIndexingRequest(
            provider_id="provider-1",
            model="embed-model",
            documents=[Document(document_id="doc-1", content="hello")],
            chunk_size=4,
            chunk_overlap=4,
        )
