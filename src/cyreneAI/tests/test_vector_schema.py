from __future__ import annotations

import pytest
from pydantic import ValidationError

from cyreneAI.core.schema.vector import (
    VectorQuery,
    VectorRecord,
    VectorSearchMatch,
    VectorSearchResult,
)


def test_vector_schema_defaults_are_isolated() -> None:
    first_record = VectorRecord(record_id="record-1", vector=[1.0, 0.0])
    second_record = VectorRecord(record_id="record-2", vector=[0.0, 1.0])
    first_record.metadata["kind"] = "doc"

    first_query = VectorQuery(vector=[1.0, 0.0])
    second_query = VectorQuery(vector=[1.0, 0.0])
    first_query.filters["kind"] = "doc"

    result = VectorSearchResult()
    result.matches.append(
        VectorSearchMatch(
            record=first_record,
            score=1.0,
        )
    )
    another_result = VectorSearchResult()

    assert second_record.metadata == {}
    assert second_query.filters == {}
    assert first_query.top_k == 5
    assert another_result.matches == []


def test_vector_schema_rejects_empty_vectors_and_invalid_top_k() -> None:
    with pytest.raises(ValidationError):
        VectorRecord(record_id="record-1", vector=[])

    with pytest.raises(ValidationError):
        VectorQuery(vector=[])

    with pytest.raises(ValidationError):
        VectorQuery(vector=[1.0], top_k=0)
