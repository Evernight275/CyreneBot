from __future__ import annotations

from typing import Any, cast

from cyreneAI.application.chat.orchestrator import ChatOrchestrator
from cyreneAI.application.knowledge.retrieval_orchestrator import RetrievalOrchestrator
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.schema.application import (
    ApplicationChatRequest,
    ApplicationRAGChatRequest,
    ApplicationRAGChatResult,
    ApplicationRetrievalRequest,
    RAGContextFormat,
)
from cyreneAI.core.schema.context import (
    ContextItem,
    ContextItemSource,
    ContextItemType,
    ContextSegment,
    ContextSegmentRole,
)
from cyreneAI.core.schema.message import ContentPart, Message
from cyreneAI.core.schema.vector import VectorSearchMatch


class RAGChatOrchestrator:
    """
    应用 RAG 聊天编排器
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._runtime = runtime
        self._retrieval_orchestrator = RetrievalOrchestrator(runtime)
        self._chat_orchestrator = ChatOrchestrator(runtime)

    async def chat(
        self,
        request: ApplicationRAGChatRequest,
    ) -> ApplicationRAGChatResult:
        """
        编排一次 retrieval -> context -> chat 请求。
        """
        retrieval_query = request.retrieval_query or _messages_to_text(request.messages)
        retrieval_result = await self._retrieval_orchestrator.retrieve(
            ApplicationRetrievalRequest(
                provider_id=request.retrieval_provider_id,
                model=request.retrieval_model,
                query=retrieval_query,
                dimensions=request.retrieval_dimensions,
                top_k=request.retrieval_top_k,
                filters=request.retrieval_filters.copy(),
                min_score=request.retrieval_min_score,
                collection_id=request.collection_id,
                metadata={
                    **request.metadata,
                    "session_id": request.session_id,
                },
            )
        )
        retrieved_segment = _build_retrieved_context_segment(
            session_id=request.session_id,
            matches=retrieval_result.search_result.matches,
            context_format=request.retrieval_context_format,
            max_content_chars=request.max_retrieved_content_chars,
            include_metadata=request.include_retrieval_metadata,
        )
        chat_result = await self._chat_orchestrator.chat(
            ApplicationChatRequest(
                session_id=request.session_id,
                provider_id=request.provider_id,
                model=request.model,
                messages=request.messages,
                context_budget=request.context_budget,
                required_skill_names=request.required_skill_names,
                max_skills=request.max_skills,
                additional_context_segments=[retrieved_segment],
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                stream=request.stream,
                tool_choice=request.tool_choice,
                allowed_tool_names=request.allowed_tool_names,
                tool_execution_policy=request.tool_execution_policy,
                max_tool_rounds=request.max_tool_rounds,
                metadata={
                    **request.metadata,
                    **_collection_metadata(request.collection_id),
                    "retrieval_match_count": len(
                        retrieval_result.search_result.matches
                    ),
                },
            )
        )
        return ApplicationRAGChatResult(
            chat_result=chat_result,
            retrieval_result=retrieval_result,
            metadata={
                **request.metadata,
                **_collection_metadata(request.collection_id),
                "retrieval_match_count": len(retrieval_result.search_result.matches),
            },
        )


def _build_retrieved_context_segment(
    *,
    session_id: str,
    matches: list[VectorSearchMatch],
    context_format: RAGContextFormat,
    max_content_chars: int | None,
    include_metadata: bool,
) -> ContextSegment:
    return ContextSegment(
        segment_id=f"{session_id}:retrieved",
        role=ContextSegmentRole.RETRIEVED,
        items=[
            ContextItem(
                item_id=f"{session_id}:retrieved:{index}",
                type=ContextItemType.RETRIEVED,
                source=ContextItemSource.RETRIEVER,
                content=_format_retrieved_content(
                    match=match,
                    index=index,
                    context_format=context_format,
                    max_content_chars=max_content_chars,
                    include_metadata=include_metadata,
                ),
                priority=int(match.score * 1000),
                metadata={
                    **match.record.metadata,
                    **match.metadata,
                    "record_id": match.record.record_id,
                    "score": match.score,
                },
            )
            for index, match in enumerate(matches)
        ],
        metadata={
            "match_count": len(matches),
        },
    )


def _format_retrieved_content(
    *,
    match: VectorSearchMatch,
    index: int,
    context_format: RAGContextFormat,
    max_content_chars: int | None,
    include_metadata: bool,
) -> str:
    content = _truncate_text(
        _match_content(match),
        max_chars=max_content_chars,
    )
    metadata = _format_retrieval_metadata(match) if include_metadata else None

    if context_format == RAGContextFormat.NUMBERED:
        return _join_context_lines(
            [
                f"[{index + 1}] {content}",
                metadata,
            ]
        )
    if context_format == RAGContextFormat.SOURCE_TAGGED:
        source_label = _source_label(match)
        return _join_context_lines(
            [
                f"[{source_label}]",
                metadata,
                content,
            ]
        )
    if context_format == RAGContextFormat.COMPACT:
        compact_content = " ".join(content.split())
        compact_metadata = (
            _compact_retrieval_metadata(match) if include_metadata else None
        )
        compact_parts = [f"{index + 1}. {compact_content}"]
        if compact_metadata:
            compact_parts.append(compact_metadata)
        return " | ".join(compact_parts)

    return _join_context_lines(
        [
            content,
            metadata,
        ]
    )


def _match_content(match: VectorSearchMatch) -> str:
    content = match.record.content
    if content is not None:
        return content
    return f"[vector record: {match.record.record_id}]"


def _truncate_text(text: str, *, max_chars: int | None) -> str:
    if max_chars is None or len(text) <= max_chars:
        return text
    return text[:max_chars]


def _source_label(match: VectorSearchMatch) -> str:
    metadata = {
        **match.record.metadata,
        **match.metadata,
    }
    source = metadata.get("source")
    document_id = metadata.get("document_id")
    chunk_id = metadata.get("chunk_id")
    if source:
        return f"source: {source}"
    if document_id:
        return f"document: {document_id}"
    if chunk_id:
        return f"chunk: {chunk_id}"
    return f"record: {match.record.record_id}"


def _format_retrieval_metadata(match: VectorSearchMatch) -> str:
    metadata = _retrieval_metadata(match)
    if not metadata:
        return ""
    return "metadata: " + ", ".join(
        f"{key}={value}" for key, value in metadata.items()
    )


def _compact_retrieval_metadata(match: VectorSearchMatch) -> str:
    metadata = _retrieval_metadata(match)
    if not metadata:
        return ""
    return ", ".join(f"{key}={value}" for key, value in metadata.items())


def _retrieval_metadata(match: VectorSearchMatch) -> dict[str, Any]:
    merged_metadata = {
        **match.record.metadata,
        **match.metadata,
    }
    metadata: dict[str, Any] = {}
    for key in ["source", "document_id", "chunk_id"]:
        value = merged_metadata.get(key)
        if value is not None:
            metadata[key] = value
    metadata["record_id"] = match.record.record_id
    metadata["score"] = round(match.score, 6)
    return metadata


def _join_context_lines(lines: list[str | None]) -> str:
    return "\n".join(line for line in lines if line)


def _collection_metadata(collection_id: str | None) -> dict[str, str]:
    if collection_id is None:
        return {}
    return {"collection_id": collection_id}


def _messages_to_text(messages: list[Message]) -> str:
    chunks: list[str] = []
    for message in messages:
        content = cast(list[ContentPart], message.content or [])
        for part in content:
            if part.text:
                chunks.append(part.text)
    return "\n".join(chunks)
