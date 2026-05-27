from __future__ import annotations

from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.provider_protocol import ProviderInstanceProtocol
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.infra.adapters.providers.openai_compatible.builder import (
    build_openai_compatible_provider,
)
from cyreneAI.infra.provider_catalog.openai_compatible_info import (
    OPENAI_COMPATIBLE_PROVIDER_INFO,
)


async def _build_openai_compatible_provider_with_info(
    config: ProviderConfig,
) -> ProviderInstanceProtocol:
    return await build_openai_compatible_provider(
        config=config,
        info=OPENAI_COMPATIBLE_PROVIDER_INFO,
    )


def register_openai_compatible_provider(
    registry: ProviderRegistry,
    factory: ProviderFactory,
) -> None:
    registry.register_provider(OPENAI_COMPATIBLE_PROVIDER_INFO)
    factory.register(
        ProviderType.OPENAI_COMPATIBLE,
        _build_openai_compatible_provider_with_info,
    )
