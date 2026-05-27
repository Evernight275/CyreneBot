from __future__ import annotations

import asyncio
from datetime import timedelta

from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.infra.bootstrap.registrations.openai_compatible import (
    register_openai_compatible_provider,
)


async def main() -> None:
    registry = ProviderRegistry()
    factory = ProviderFactory()

    register_openai_compatible_provider(registry, factory)

    assert registry.exists(ProviderType.OPENAI_COMPATIBLE)
    assert factory.exists(ProviderType.OPENAI_COMPATIBLE)

    manager = ProviderManager(factory)
    config = ProviderConfig(
        provider_id="test",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        api_key="test-key",
        base_url="https://example.com/v1",
        timeout=timedelta(seconds=5),
    )

    instance = await manager.add(config)
    assert instance.info.provider_type == ProviderType.OPENAI_COMPATIBLE
    assert manager.exists("test")

    await manager.close_all()
    assert not manager.exists("test")


def test_openai_compatible_minimal_provider_lifecycle() -> None:
    asyncio.run(main())
