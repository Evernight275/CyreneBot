from __future__ import annotations

from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.provider_protocol import ProviderInstanceProtocol
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.infra.adapters.providers.anthropic.builder import (
    build_anthropic_provider,
)
from cyreneAI.infra.provider_catalog.anthropic_info import ANTHROPIC_PROVIDER_INFO


async def _build_anthropic_provider_with_info(
    config: ProviderConfig,
) -> ProviderInstanceProtocol:
    return await build_anthropic_provider(
        config=config,
        info=ANTHROPIC_PROVIDER_INFO,
    )


def register_anthropic_provider(
    registry: ProviderRegistry,
    factory: ProviderFactory,
) -> None:
    registry.register_provider(ANTHROPIC_PROVIDER_INFO)
    factory.register(
        ProviderType.ANTHROPIC,
        _build_anthropic_provider_with_info,
    )
