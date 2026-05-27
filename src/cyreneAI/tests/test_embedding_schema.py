from __future__ import annotations

import pytest
from pydantic import ValidationError

from cyreneAI.core.schema.embedding import (
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingVector,
)


def test_embedding_request_and_response_defaults_are_isolated() -> None:
    first_request = EmbeddingRequest(
        provider_id="provider-1",
        model="embed-model",
        input="hello",
    )
    second_request = EmbeddingRequest(
        provider_id="provider-1",
        model="embed-model",
        input=["world"],
    )
    first_request.metadata["key"] = "value"

    first_response = EmbeddingResponse(provider_id="provider-1")
    second_response = EmbeddingResponse(provider_id="provider-1")
    first_response.embeddings.append(
        EmbeddingVector(index=0, embedding=[0.1, 0.2])
    )

    assert second_request.metadata == {}
    assert second_response.embeddings == []


def test_embedding_schema_rejects_invalid_dimensions_and_index() -> None:
    with pytest.raises(ValidationError):
        EmbeddingRequest(
            provider_id="provider-1",
            model="embed-model",
            input="hello",
            dimensions=0,
        )

    with pytest.raises(ValidationError):
        EmbeddingVector(index=-1, embedding=[0.1])
