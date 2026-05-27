from __future__ import annotations

import pytest
from pydantic import ValidationError

from cyreneAI.core.schema.document import Document, DocumentChunk


def test_document_schema_defaults_are_isolated() -> None:
    first = Document(document_id="doc-1", content="hello")
    second = Document(document_id="doc-2", content="world")
    first.metadata["source"] = "test"

    chunk = DocumentChunk(
        chunk_id="doc-1:chunk:0",
        document_id="doc-1",
        index=0,
        content="hello",
    )
    another_chunk = DocumentChunk(
        chunk_id="doc-2:chunk:0",
        document_id="doc-2",
        index=0,
        content="world",
    )
    chunk.metadata["source"] = "test"

    assert second.metadata == {}
    assert another_chunk.metadata == {}


def test_document_schema_rejects_empty_content_and_invalid_index() -> None:
    with pytest.raises(ValidationError):
        Document(document_id="doc-1", content="")

    with pytest.raises(ValidationError):
        DocumentChunk(
            chunk_id="doc-1:chunk:0",
            document_id="doc-1",
            index=-1,
            content="hello",
        )

    with pytest.raises(ValidationError):
        DocumentChunk(
            chunk_id="doc-1:chunk:0",
            document_id="doc-1",
            index=0,
            content="",
        )
