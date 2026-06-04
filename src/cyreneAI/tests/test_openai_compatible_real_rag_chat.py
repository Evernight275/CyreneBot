# ----------------------------------------------------
# 此测试旨在测试能不能在真实情况跑通，不做强制要求
# ----------------------------------------------------
from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import pytest
from dotenv import load_dotenv

from cyreneAI.application.chat.rag_orchestrator import (
    ApplicationRAGChatRequest,
    RAGChatOrchestrator,
)
from cyreneAI.application.knowledge.indexing_orchestrator import (
    ApplicationIndexingRequest,
    IndexingOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.chat import ChatFinishReason
from cyreneAI.core.schema.document import Document
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.core.vector.manager import VectorManager
from cyreneAI.infra.adapters.vector_stores.memory.store import InMemoryVectorStore
from cyreneAI.infra.bootstrap.registrations.openai_compatible import (
    register_openai_compatible_provider,
)


async def _run_real_rag_chat() -> None:
    load_dotenv()

    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    chat_model = os.getenv("OPENAI_COMPATIBLE_MODEL") or os.getenv("OPENAI_MODEL")
    embedding_model = os.getenv("OPENAI_COMPATIBLE_EMBEDDING_MODEL") or os.getenv(
        "OPENAI_EMBEDDING_MODEL"
    )

    if not api_key:
        pytest.skip("OPENAI_COMPATIBLE_API_KEY or OPENAI_API_KEY is required")
    if not chat_model:
        pytest.skip("OPENAI_COMPATIBLE_MODEL or OPENAI_MODEL is required")
    if not embedding_model:
        pytest.skip(
            "OPENAI_COMPATIBLE_EMBEDDING_MODEL or OPENAI_EMBEDDING_MODEL is required"
        )

    registry = ProviderRegistry()
    factory = ProviderFactory()
    register_openai_compatible_provider(registry, factory)

    manager = ProviderManager(factory)
    config = ProviderConfig(
        provider_id="real-openai-compatible-rag",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        api_key=api_key,
        base_url=base_url,
        timeout=timedelta(seconds=30),
    )
    runtime = CyreneAIRuntime(
        provider_manager=manager,
        context_builder=ContextWindowBuilder(),
        vector_manager=VectorManager(InMemoryVectorStore()),
    )

    try:
        await manager.add(config)
        await IndexingOrchestrator(runtime).index(
            ApplicationIndexingRequest(
                provider_id=config.provider_id,
                model=embedding_model,
                documents=[
                    Document(
                        document_id="rag-doc-1",
                        content=(
                            "CyreneAI RAG integration test beacon color is violet."
                        ),
                        metadata={"source": "real-rag-test"},
                    )
                ],
                metadata={"purpose": "real-rag-test"},
            )
        )
        result = await RAGChatOrchestrator(runtime).chat(
            ApplicationRAGChatRequest(
                session_id="real-rag-session",
                provider_id=config.provider_id,
                model=chat_model,
                retrieval_provider_id=config.provider_id,
                retrieval_model=embedding_model,
                messages=[
                    Message(
                        role=MessageRole.USER,
                        content=[
                            ContentPart(
                                type=ContentPartType.TEXT,
                                text=(
                                    "Using the retrieved context, what is the "
                                    "CyreneAI RAG integration test beacon color?"
                                ),
                            )
                        ],
                    )
                ],
                retrieval_top_k=1,
                temperature=0,
                max_tokens=32,
                metadata={"purpose": "real-rag-test"},
            )
        )

        response = result.chat_result.response
        assert result.retrieval_result.search_result.matches
        assert response.provider_id == config.provider_id
        assert response.finish_reason in {
            ChatFinishReason.STOP,
            ChatFinishReason.LENGTH,
        }
        assert response.message is not None
        assert response.message.content is not None
        assert response.message.content[0].text

        print()
        print("openai-compatible real rag response:")
        print(f"  chat_model: {response.model}")
        print(f"  embedding_model: {embedding_model}")
        print(f"  finish_reason: {response.finish_reason}")
        print(f"  matches: {len(result.retrieval_result.search_result.matches)}")
        print(f"  text: {response.message.content[0].text}")
    finally:
        await manager.close_all()
        if runtime.vector_manager is not None:
            await runtime.vector_manager.close()


def test_openai_compatible_real_rag_chat() -> None:
    asyncio.run(_run_real_rag_chat())
