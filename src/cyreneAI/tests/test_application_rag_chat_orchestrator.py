from __future__ import annotations

import asyncio
from datetime import timedelta

from cyreneAI.application.rag_chat_orchestrator import (
    ApplicationRAGChatRequest,
    RAGContextFormat,
    RAGChatOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest, ChatResponse
from cyreneAI.core.schema.embedding import (
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingVector,
)
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType
from cyreneAI.core.schema.tool import ToolCall, ToolDefinition, ToolResult
from cyreneAI.core.schema.vector import VectorRecord
from cyreneAI.core.schema.context import ContextSegmentRole
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.registry import ToolRegistry
from cyreneAI.core.vector.manager import VectorManager
from cyreneAI.infra.adapters.vector_stores.memory.store import InMemoryVectorStore


def _message(role: MessageRole, text: str) -> Message:
    return Message(
        role=role,
        content=[
            ContentPart(
                type=ContentPartType.TEXT,
                text=text,
            )
        ],
    )


class FakeRAGProvider:
    info = ProviderInfo(
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        name="fake",
        description="Fake RAG provider.",
    )
    config = ProviderConfig(
        provider_id="provider-1",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        timeout=timedelta(seconds=1),
    )

    def __init__(self) -> None:
        self.chat_requests: list[ChatRequest] = []
        self.embedding_requests: list[EmbeddingRequest] = []

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.chat_requests.append(request)
        return ChatResponse(
            provider_id=request.provider_id,
            model=request.model,
            message=_message(MessageRole.ASSISTANT, "answer"),
            finish_reason=ChatFinishReason.STOP,
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.embedding_requests.append(request)
        return EmbeddingResponse(
            provider_id=request.provider_id,
            model=request.model,
            embeddings=[
                EmbeddingVector(index=0, embedding=[1.0, 0.0]),
            ],
        )

    async def close(self) -> None:
        pass


class FakeToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=f"executed:{call.name}",
        )


async def _build_provider_manager(provider: FakeRAGProvider) -> ProviderManager:
    factory = ProviderFactory()

    async def build_provider(config: ProviderConfig) -> FakeRAGProvider:
        return provider

    factory.register(ProviderType.OPENAI_COMPATIBLE, build_provider)
    manager = ProviderManager(factory)
    await manager.add(provider.config)
    return manager


async def _build_runtime(
    provider: FakeRAGProvider,
    records: list[VectorRecord] | None = None,
) -> CyreneAIRuntime:
    store = InMemoryVectorStore()
    await store.upsert(
        records
        or [
            VectorRecord(
                record_id="doc-1:chunk:0",
                vector=[1.0, 0.0],
                content="CyreneAI keeps provider adapters out of core.",
                metadata={
                    "document_id": "doc-1",
                    "chunk_id": "doc-1:chunk:0",
                    "source": "unit",
                    "collection_id": "collection-1",
                },
            )
        ]
    )
    return CyreneAIRuntime(
        provider_manager=await _build_provider_manager(provider),
        context_builder=ContextWindowBuilder(),
        vector_manager=VectorManager(store),
    )


def test_rag_chat_orchestrator_retrieves_context_and_calls_chat_provider() -> None:
    async def run() -> None:
        provider = FakeRAGProvider()
        runtime = await _build_runtime(provider)

        result = await RAGChatOrchestrator(runtime).chat(
            ApplicationRAGChatRequest(
                session_id="session-1",
                provider_id="provider-1",
                model="chat-model",
                retrieval_provider_id="provider-1",
                retrieval_model="embed-model",
                messages=[_message(MessageRole.USER, "Where do adapters live?")],
                retrieval_top_k=1,
                collection_id="collection-1",
                metadata={"purpose": "rag"},
            )
        )

        assert provider.embedding_requests == [
            EmbeddingRequest(
                provider_id="provider-1",
                model="embed-model",
                input="Where do adapters live?",
                dimensions=None,
                metadata={
                    "purpose": "rag",
                    "session_id": "session-1",
                    "collection_id": "collection-1",
                },
            )
        ]
        assert result.chat_result.response.message == _message(
            MessageRole.ASSISTANT,
            "answer",
        )
        assert result.metadata == {
            "purpose": "rag",
            "collection_id": "collection-1",
            "retrieval_match_count": 1,
        }

        chat_request = provider.chat_requests[0]
        assert chat_request.provider_id == "provider-1"
        assert chat_request.model == "chat-model"
        assert chat_request.metadata["collection_id"] == "collection-1"
        assert chat_request.metadata["retrieval_match_count"] == 1
        assert [message.role for message in chat_request.messages] == [
            MessageRole.USER,
            MessageRole.SYSTEM,
        ]
        assert chat_request.messages[0].content is not None
        assert chat_request.messages[0].content[0].text == "Where do adapters live?"
        assert chat_request.messages[1].content is not None
        assert chat_request.messages[1].content[0].text == (
            "CyreneAI keeps provider adapters out of core."
        )

        snapshot = result.chat_result.context_snapshot
        assert [segment.role for segment in snapshot.window.segments] == [
            ContextSegmentRole.HISTORY,
            ContextSegmentRole.RETRIEVED,
        ]
        retrieved_segment = snapshot.window.segments[1]
        assert retrieved_segment.metadata == {"match_count": 1}
        assert retrieved_segment.items[0].metadata["record_id"] == "doc-1:chunk:0"
        assert retrieved_segment.items[0].metadata["score"] == 1.0

    asyncio.run(run())


def test_rag_chat_orchestrator_passes_allowed_tool_names_to_chat() -> None:
    async def run() -> None:
        provider = FakeRAGProvider()
        runtime = await _build_runtime(provider)
        tool_registry = ToolRegistry()
        tool_registry.register(
            ToolDefinition(name="lookup", description="Lookup a value."),
            FakeToolExecutor(),
        )
        tool_registry.register(
            ToolDefinition(name="delete", description="Delete a value."),
            FakeToolExecutor(),
        )
        runtime.tool_registry = tool_registry
        runtime.tool_manager = ToolManager(tool_registry)

        await RAGChatOrchestrator(runtime).chat(
            ApplicationRAGChatRequest(
                session_id="session-1",
                provider_id="provider-1",
                model="chat-model",
                retrieval_provider_id="provider-1",
                retrieval_model="embed-model",
                messages=[_message(MessageRole.USER, "Where do adapters live?")],
                retrieval_top_k=1,
                collection_id="collection-1",
                allowed_tool_names=["lookup"],
            )
        )

        chat_tools = provider.chat_requests[0].tools
        assert chat_tools is not None
        assert [tool.name for tool in chat_tools] == ["lookup"]

    asyncio.run(run())


def test_rag_chat_orchestrator_formats_numbered_truncated_context() -> None:
    async def run() -> None:
        provider = FakeRAGProvider()
        runtime = await _build_runtime(
            provider,
            records=[
                VectorRecord(
                    record_id="record-1",
                    vector=[1.0, 0.0],
                    content="abcdefghijklmnopqrstuvwxyz",
                    metadata={
                        "source": "unit",
                        "document_id": "doc-1",
                        "chunk_id": "chunk-1",
                    },
                )
            ],
        )

        await RAGChatOrchestrator(runtime).chat(
            ApplicationRAGChatRequest(
                session_id="session-1",
                provider_id="provider-1",
                model="chat-model",
                retrieval_provider_id="provider-1",
                retrieval_model="embed-model",
                messages=[_message(MessageRole.USER, "Find alpha.")],
                retrieval_context_format=RAGContextFormat.NUMBERED,
                max_retrieved_content_chars=5,
                include_retrieval_metadata=True,
            )
        )

        content = provider.chat_requests[0].messages[1].content
        assert content is not None
        assert content[0].text == (
            "[1] abcde\n"
            "metadata: source=unit, document_id=doc-1, chunk_id=chunk-1, "
            "record_id=record-1, score=1.0"
        )

    asyncio.run(run())


def test_rag_chat_orchestrator_formats_source_tagged_context() -> None:
    async def run() -> None:
        provider = FakeRAGProvider()
        runtime = await _build_runtime(provider)

        await RAGChatOrchestrator(runtime).chat(
            ApplicationRAGChatRequest(
                session_id="session-1",
                provider_id="provider-1",
                model="chat-model",
                retrieval_provider_id="provider-1",
                retrieval_model="embed-model",
                messages=[_message(MessageRole.USER, "Find alpha.")],
                retrieval_context_format=RAGContextFormat.SOURCE_TAGGED,
                include_retrieval_metadata=True,
            )
        )

        content = provider.chat_requests[0].messages[1].content
        assert content is not None
        assert content[0].text == (
            "[source: unit]\n"
            "metadata: source=unit, document_id=doc-1, "
            "chunk_id=doc-1:chunk:0, record_id=doc-1:chunk:0, score=1.0\n"
            "CyreneAI keeps provider adapters out of core."
        )

    asyncio.run(run())


def test_rag_chat_orchestrator_formats_compact_context_with_content_fallback() -> None:
    async def run() -> None:
        provider = FakeRAGProvider()
        runtime = await _build_runtime(
            provider,
            records=[
                VectorRecord(
                    record_id="record-1",
                    vector=[1.0, 0.0],
                    metadata={"source": "unit"},
                )
            ],
        )

        await RAGChatOrchestrator(runtime).chat(
            ApplicationRAGChatRequest(
                session_id="session-1",
                provider_id="provider-1",
                model="chat-model",
                retrieval_provider_id="provider-1",
                retrieval_model="embed-model",
                messages=[_message(MessageRole.USER, "Find alpha.")],
                retrieval_context_format=RAGContextFormat.COMPACT,
            )
        )

        content = provider.chat_requests[0].messages[1].content
        assert content is not None
        assert content[0].text == "1. [vector record: record-1]"

    asyncio.run(run())
