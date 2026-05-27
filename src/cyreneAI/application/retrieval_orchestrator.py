from __future__ import annotations

from typing import Any, cast

from pydantic import Field

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import StateError, UnsupportedError
from cyreneAI.core.provider.provider_protocol import EmbeddingProviderProtocol
from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.embedding import EmbeddingRequest, EmbeddingResponse
from cyreneAI.core.schema.vector import VectorQuery, VectorSearchResult
from cyreneAI.core.vector.manager import VectorManager


class ApplicationRetrievalRequest(CyreneAISchema):
    """
    应用检索请求
    """

    provider_id: str
    model: str
    query: str
    dimensions: int | None = Field(default=None, ge=1)
    top_k: int = Field(default=5, ge=1)
    filters: dict[str, Any] = Field(default_factory=dict)
    min_score: float | None = None
    collection_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationRetrievalResult(CyreneAISchema):
    """
    应用检索结果
    """

    embedding_response: EmbeddingResponse
    search_result: VectorSearchResult
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalOrchestrator:
    """
    应用检索编排器
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._runtime = runtime

    async def retrieve(
        self,
        request: ApplicationRetrievalRequest,
    ) -> ApplicationRetrievalResult:
        """
        编排一次语义检索请求。
        """
        embedding_provider = self._get_embedding_provider(request.provider_id)
        vector_manager = self._get_vector_manager()

        embedding_response = await embedding_provider.embed(
            EmbeddingRequest(
                provider_id=request.provider_id,
                model=request.model,
                input=request.query,
                dimensions=request.dimensions,
                metadata={
                    **request.metadata,
                    **_collection_metadata(request.collection_id),
                },
            )
        )
        if not embedding_response.embeddings:
            raise StateError("Embedding response is empty")

        query_vector = embedding_response.embeddings[0].embedding
        search_result = await vector_manager.search(
            VectorQuery(
                vector=query_vector,
                top_k=request.top_k,
                filters=_merge_collection_filter(
                    filters=request.filters,
                    collection_id=request.collection_id,
                ),
                min_score=request.min_score,
                metadata={
                    **request.metadata,
                    **_collection_metadata(request.collection_id),
                },
            )
        )
        return ApplicationRetrievalResult(
            embedding_response=embedding_response,
            search_result=search_result,
            metadata={
                **request.metadata,
                **_collection_metadata(request.collection_id),
                "match_count": len(search_result.matches),
            },
        )

    def _get_embedding_provider(self, provider_id: str) -> EmbeddingProviderProtocol:
        provider = self._runtime.provider_manager.get(provider_id)
        embed = getattr(provider, "embed", None)
        if embed is None:
            raise UnsupportedError(f"Provider {provider_id} does not support embedding")
        return cast(EmbeddingProviderProtocol, provider)

    def _get_vector_manager(self) -> VectorManager:
        if self._runtime.vector_manager is None:
            raise StateError("Vector manager is not set")
        return self._runtime.vector_manager


def _merge_collection_filter(
    *,
    filters: dict[str, Any],
    collection_id: str | None,
) -> dict[str, Any]:
    merged = filters.copy()
    if collection_id is None:
        return merged
    existing_collection_id = merged.get("collection_id")
    if existing_collection_id is not None and existing_collection_id != collection_id:
        raise ValueError("filters.collection_id conflicts with collection_id")
    merged["collection_id"] = collection_id
    return merged


def _collection_metadata(collection_id: str | None) -> dict[str, str]:
    if collection_id is None:
        return {}
    return {"collection_id": collection_id}
