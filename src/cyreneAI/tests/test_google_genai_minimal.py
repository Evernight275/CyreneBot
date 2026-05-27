from __future__ import annotations

import asyncio
from datetime import timedelta

from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.infra.bootstrap.registrations.google_genai import (
    register_google_genai_provider,
)


async def main() -> None:
    registry = ProviderRegistry()
    factory = ProviderFactory()

    register_google_genai_provider(registry, factory)

    assert registry.exists(ProviderType.GOOGLE)
    assert factory.exists(ProviderType.GOOGLE)

    manager = ProviderManager(factory)
    config = ProviderConfig(
        provider_id="test",
        provider_type=ProviderType.GOOGLE,
        api_key="test-key",
        timeout=timedelta(seconds=5),
    )

    instance = await manager.add(config)
    assert instance.info.provider_type == ProviderType.GOOGLE
    assert manager.exists("test")

    await manager.close_all()
    assert not manager.exists("test")


def test_google_genai_minimal_provider_lifecycle() -> None:
    asyncio.run(main())
