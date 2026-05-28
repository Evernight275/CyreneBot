from __future__ import annotations

from typing import Any, cast

from pydantic import Field

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import UnsupportedError
from cyreneAI.core.provider.provider_protocol import EmbeddingProviderProtocol
from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.embedding import EmbeddingRequest, EmbeddingResponse


class ApplicationEmbeddingRequest(CyreneAISchema):
    """
    应用嵌入请求
    """

    provider_id: str
    model: str
    input: str | list[str]
    dimensions: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationEmbeddingResult(CyreneAISchema):
    """
    应用嵌入结果
    """

    response: EmbeddingResponse
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddingOrchestrator:
    """
    应用嵌入编排器
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._runtime = runtime

    async def embed(
        self,
        request: ApplicationEmbeddingRequest,
    ) -> ApplicationEmbeddingResult:
        """
        编排一次嵌入请求。
        """
        provider_request = EmbeddingRequest(
            provider_id=request.provider_id,
            model=request.model,
            input=request.input,
            dimensions=request.dimensions,
            metadata=request.metadata.copy(),
        )
        provider = self._get_embedding_provider(request.provider_id)
        response = await provider.embed(provider_request)
        return ApplicationEmbeddingResult(
            response=response,
            metadata={
                **request.metadata,
                "embedding_count": len(response.embeddings),
            },
        )

    def _get_embedding_provider(self, provider_id: str) -> EmbeddingProviderProtocol:
        provider = self._runtime.provider_manager.get(provider_id)
        embed = getattr(provider, "embed", None)
        if embed is None:
            raise UnsupportedError(f"Provider {provider_id} does not support embedding")
        return cast(EmbeddingProviderProtocol, provider)
