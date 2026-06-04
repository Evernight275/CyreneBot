from __future__ import annotations

import asyncio

import pytest

from cyreneAI.application.knowledge.vector_store_orchestrator import (
    ApplicationVectorSearchRequest,
    ApplicationVectorUpsertRequest,
    VectorStoreOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.errors.base import StateError
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.vector import VectorRecord
from cyreneAI.core.vector.manager import VectorManager
from cyreneAI.infra.adapters.vector_stores.memory.store import InMemoryVectorStore


async def _build_runtime(*, with_vector_store: bool = True) -> CyreneAIRuntime:
    runtime = CyreneAIRuntime(
        provider_manager=ProviderManager(ProviderFactory()),
        context_builder=ContextWindowBuilder(),
    )
    if with_vector_store:
        runtime.vector_manager = VectorManager(InMemoryVectorStore())
    return runtime


async def _run_vector_store_orchestrator_lifecycle() -> None:
    runtime = await _build_runtime()
    orchestrator = VectorStoreOrchestrator(runtime)

    upsert_result = await orchestrator.upsert(
        ApplicationVectorUpsertRequest(
            records=[
                VectorRecord(
                    record_id="record-1",
                    vector=[1.0, 0.0],
                    content="alpha",
                ),
                VectorRecord(
                    record_id="record-2",
                    vector=[0.0, 1.0],
                    content="beta",
                ),
            ],
            metadata={"source": "test"},
        )
    )

    assert upsert_result.metadata == {
        "source": "test",
        "record_count": 2,
    }
    assert (await orchestrator.get("record-1")).record.content == "alpha"

    search_result = await orchestrator.search(
        ApplicationVectorSearchRequest(
            vector=[1.0, 0.0],
            top_k=1,
            metadata={"purpose": "rag"},
        )
    )

    assert [match.record.record_id for match in search_result.result.matches] == [
        "record-1"
    ]
    assert search_result.metadata == {
        "purpose": "rag",
        "match_count": 1,
    }

    delete_result = await orchestrator.delete("record-1")

    assert delete_result.metadata == {
        "record_id": "record-1",
        "deleted": True,
    }


def test_vector_store_orchestrator_runs_vector_store_lifecycle() -> None:
    asyncio.run(_run_vector_store_orchestrator_lifecycle())


async def _run_vector_store_orchestrator_requires_manager() -> None:
    orchestrator = VectorStoreOrchestrator(
        await _build_runtime(with_vector_store=False)
    )

    with pytest.raises(StateError):
        await orchestrator.search(ApplicationVectorSearchRequest(vector=[1.0]))


def test_vector_store_orchestrator_requires_vector_manager() -> None:
    asyncio.run(_run_vector_store_orchestrator_requires_manager())
