from __future__ import annotations

from enum import StrEnum
import re
from typing import Any, cast

from pydantic import Field, model_validator

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import StateError, UnsupportedError
from cyreneAI.core.provider.provider_protocol import EmbeddingProviderProtocol
from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.document import Document, DocumentChunk
from cyreneAI.core.schema.embedding import EmbeddingRequest, EmbeddingResponse
from cyreneAI.core.schema.vector import VectorRecord
from cyreneAI.core.vector.manager import VectorManager


class ChunkStrategy(StrEnum):
    """
    文档切块策略
    """

    CHARACTER = "character"
    PARAGRAPH = "paragraph"


class ApplicationIndexingRequest(CyreneAISchema):
    """
    应用索引请求
    """

    provider_id: str
    model: str
    documents: list[Document] = Field(min_length=1)
    chunk_size: int = Field(default=1000, ge=1)
    chunk_overlap: int = Field(default=0, ge=0)
    chunk_strategy: ChunkStrategy = ChunkStrategy.CHARACTER
    dimensions: int | None = Field(default=None, ge=1)
    collection_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "ApplicationIndexingRequest":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class ApplicationIndexingResult(CyreneAISchema):
    """
    应用索引结果
    """

    chunks: list[DocumentChunk] = Field(default_factory=list)
    records: list[VectorRecord] = Field(default_factory=list)
    embedding_response: EmbeddingResponse
    metadata: dict[str, Any] = Field(default_factory=dict)


class IndexingOrchestrator:
    """
    应用索引编排器
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._runtime = runtime

    async def index(
        self,
        request: ApplicationIndexingRequest,
    ) -> ApplicationIndexingResult:
        """
        编排一次文档索引请求。
        """
        chunks = _chunk_documents(
            documents=request.documents,
            chunk_size=request.chunk_size,
            chunk_overlap=request.chunk_overlap,
            chunk_strategy=request.chunk_strategy,
        )
        embedding_provider = self._get_embedding_provider(request.provider_id)
        vector_manager = self._get_vector_manager()

        embedding_response = await embedding_provider.embed(
            EmbeddingRequest(
                provider_id=request.provider_id,
                model=request.model,
                input=[chunk.content for chunk in chunks],
                dimensions=request.dimensions,
                metadata={
                    **request.metadata,
                    **_collection_metadata(request.collection_id),
                    "chunk_strategy": request.chunk_strategy,
                    "chunk_count": len(chunks),
                },
            )
        )
        records = _build_vector_records(
            chunks=chunks,
            embedding_response=embedding_response,
            provider_id=request.provider_id,
            model=request.model,
            collection_id=request.collection_id,
        )
        await vector_manager.upsert(records)
        return ApplicationIndexingResult(
            chunks=chunks,
            records=records,
            embedding_response=embedding_response,
            metadata={
                **request.metadata,
                **_collection_metadata(request.collection_id),
                "chunk_strategy": request.chunk_strategy,
                "document_count": len(request.documents),
                "chunk_count": len(chunks),
                "record_count": len(records),
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


def _chunk_documents(
    *,
    documents: list[Document],
    chunk_size: int,
    chunk_overlap: int,
    chunk_strategy: ChunkStrategy,
) -> list[DocumentChunk]:
    if chunk_strategy == ChunkStrategy.PARAGRAPH:
        return _chunk_documents_by_paragraph(
            documents=documents,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    return _chunk_documents_by_character(
        documents=documents,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


def _chunk_documents_by_character(
    *,
    documents: list[Document],
    chunk_size: int,
    chunk_overlap: int,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    step = chunk_size - chunk_overlap

    for document in documents:
        chunks.extend(
            _split_text_to_document_chunks(
                document=document,
                text=document.content,
                base_start=0,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                start_index=0,
                chunk_strategy=ChunkStrategy.CHARACTER,
            )
        )

    return chunks


def _chunk_documents_by_paragraph(
    *,
    documents: list[Document],
    chunk_size: int,
    chunk_overlap: int,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []

    for document in documents:
        chunk_index = 0
        pending_parts: list[str] = []
        pending_start: int | None = None
        pending_end: int | None = None

        for paragraph in _iter_paragraph_spans(document.content):
            paragraph_text = paragraph.text
            if len(paragraph_text) > chunk_size:
                chunk_index = _flush_paragraph_chunk(
                    chunks=chunks,
                    document=document,
                    parts=pending_parts,
                    start=pending_start,
                    end=pending_end,
                    chunk_index=chunk_index,
                )
                pending_parts = []
                pending_start = None
                pending_end = None
                oversized_chunks = _split_text_to_document_chunks(
                    document=document,
                    text=paragraph_text,
                    base_start=paragraph.start,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    start_index=chunk_index,
                    chunk_strategy=ChunkStrategy.PARAGRAPH,
                )
                chunks.extend(oversized_chunks)
                chunk_index += len(oversized_chunks)
                continue

            candidate_parts = [*pending_parts, paragraph_text]
            candidate_text = "\n\n".join(candidate_parts)
            if pending_parts and len(candidate_text) > chunk_size:
                chunk_index = _flush_paragraph_chunk(
                    chunks=chunks,
                    document=document,
                    parts=pending_parts,
                    start=pending_start,
                    end=pending_end,
                    chunk_index=chunk_index,
                )
                pending_parts = [paragraph_text]
                pending_start = paragraph.start
                pending_end = paragraph.end
                continue

            pending_parts = candidate_parts
            pending_start = paragraph.start if pending_start is None else pending_start
            pending_end = paragraph.end

        chunk_index = _flush_paragraph_chunk(
            chunks=chunks,
            document=document,
            parts=pending_parts,
            start=pending_start,
            end=pending_end,
            chunk_index=chunk_index,
        )

    return chunks


class _ParagraphSpan(CyreneAISchema):
    text: str
    start: int
    end: int


def _iter_paragraph_spans(text: str) -> list[_ParagraphSpan]:
    paragraphs: list[_ParagraphSpan] = []
    for match in re.finditer(r"[^\n]+(?:\n(?!\s*\n)[^\n]+)*", text):
        paragraph_text = match.group(0).strip()
        if not paragraph_text:
            continue
        leading_offset = len(match.group(0)) - len(match.group(0).lstrip())
        trailing_offset = len(match.group(0).rstrip())
        paragraphs.append(
            _ParagraphSpan(
                text=paragraph_text,
                start=match.start() + leading_offset,
                end=match.start() + trailing_offset,
            )
        )
    return paragraphs


def _flush_paragraph_chunk(
    *,
    chunks: list[DocumentChunk],
    document: Document,
    parts: list[str],
    start: int | None,
    end: int | None,
    chunk_index: int,
) -> int:
    if not parts or start is None or end is None:
        return chunk_index
    chunks.append(
        _build_document_chunk(
            document=document,
            chunk_index=chunk_index,
            content="\n\n".join(parts),
            start=start,
            end=end,
            chunk_strategy=ChunkStrategy.PARAGRAPH,
        )
    )
    return chunk_index + 1


def _split_text_to_document_chunks(
    *,
    document: Document,
    text: str,
    base_start: int,
    chunk_size: int,
    chunk_overlap: int,
    start_index: int,
    chunk_strategy: ChunkStrategy,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    step = chunk_size - chunk_overlap
    start = 0
    chunk_index = start_index

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(
            _build_document_chunk(
                document=document,
                chunk_index=chunk_index,
                content=text[start:end],
                start=base_start + start,
                end=base_start + end,
                chunk_strategy=chunk_strategy,
            )
        )
        if end == len(text):
            break
        start += step
        chunk_index += 1

    return chunks


def _build_document_chunk(
    *,
    document: Document,
    chunk_index: int,
    content: str,
    start: int,
    end: int,
    chunk_strategy: ChunkStrategy,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=f"{document.document_id}:chunk:{chunk_index}",
        document_id=document.document_id,
        index=chunk_index,
        content=content,
        metadata={
            **document.metadata,
            "document_id": document.document_id,
            "chunk_index": chunk_index,
            "chunk_strategy": chunk_strategy,
            "start": start,
            "end": end,
        },
    )


def _build_vector_records(
    *,
    chunks: list[DocumentChunk],
    embedding_response: EmbeddingResponse,
    provider_id: str,
    model: str,
    collection_id: str | None,
) -> list[VectorRecord]:
    embeddings_by_index = {
        embedding.index: embedding for embedding in embedding_response.embeddings
    }
    records: list[VectorRecord] = []

    for index, chunk in enumerate(chunks):
        embedding = embeddings_by_index.get(index)
        if embedding is None:
            raise StateError(
                f"Embedding response missing vector for chunk index {index}"
            )
        records.append(
            VectorRecord(
                record_id=chunk.chunk_id,
                vector=embedding.embedding,
                content=chunk.content,
                metadata={
                    **chunk.metadata,
                    **_collection_metadata(collection_id),
                    "chunk_id": chunk.chunk_id,
                    "embedding_provider_id": provider_id,
                    "embedding_model": embedding_response.model or model,
                },
            )
        )

    if len(records) != len(embedding_response.embeddings):
        raise StateError(
            "Embedding response count does not match indexed chunk count"
        )

    return records


def _collection_metadata(collection_id: str | None) -> dict[str, str]:
    if collection_id is None:
        return {}
    return {"collection_id": collection_id}
