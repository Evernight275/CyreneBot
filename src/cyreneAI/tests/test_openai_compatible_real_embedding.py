# ----------------------------------------------------
# 此测试旨在测试能不能在真实情况跑通，不做强制要求
# ----------------------------------------------------
from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import pytest
from dotenv import load_dotenv

from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.embedding import EmbeddingRequest
from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.infra.bootstrap.registrations.openai_compatible import (
    register_openai_compatible_provider,
)


async def _run_real_embedding() -> None:
    load_dotenv()

    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_COMPATIBLE_EMBEDDING_MODEL") or os.getenv(
        "OPENAI_EMBEDDING_MODEL"
    )

    if not api_key:
        pytest.skip("OPENAI_COMPATIBLE_API_KEY or OPENAI_API_KEY is required")
    if not model:
        pytest.skip(
            "OPENAI_COMPATIBLE_EMBEDDING_MODEL or OPENAI_EMBEDDING_MODEL is required"
        )

    registry = ProviderRegistry()
    factory = ProviderFactory()
    register_openai_compatible_provider(registry, factory)

    manager = ProviderManager(factory)
    config = ProviderConfig(
        provider_id="real-openai-compatible-embedding",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        api_key=api_key,
        base_url=base_url,
        timeout=timedelta(seconds=30),
    )

    request = EmbeddingRequest(
        provider_id=config.provider_id,
        model=model,
        input=["hello world", "good night"],
    )

    try:
        instance = await manager.add(config)
        response = await instance.embed(request)

        assert response.provider_id == config.provider_id
        assert response.model
        assert len(response.embeddings) == 2
        assert response.embeddings[0].embedding
        assert all(isinstance(value, float) for value in response.embeddings[0].embedding)

        print()
        print("openai-compatible real embedding response:")
        print(f"  model: {response.model}")
        print(f"  usage: {response.usage}")
        print(f"  dimensions: {len(response.embeddings[0].embedding)}")
    finally:
        await manager.close_all()


def test_openai_compatible_real_embedding() -> None:
    asyncio.run(_run_real_embedding())
