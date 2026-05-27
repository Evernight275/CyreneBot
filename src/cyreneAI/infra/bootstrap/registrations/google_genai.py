from __future__ import annotations

from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.provider_protocol import ProviderInstanceProtocol
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.infra.adapters.providers.google_genai.builder import (
    build_google_genai_provider,
)
from cyreneAI.infra.provider_catalog.google_genai_info import (
    GOOGLE_GENAI_PROVIDER_INFO,
)


async def _build_google_genai_provider_with_info(
    config: ProviderConfig,
) -> ProviderInstanceProtocol:
    return await build_google_genai_provider(
        config=config,
        info=GOOGLE_GENAI_PROVIDER_INFO,
    )


def register_google_genai_provider(
    registry: ProviderRegistry,
    factory: ProviderFactory,
) -> None:
    registry.register_provider(GOOGLE_GENAI_PROVIDER_INFO)
    factory.register(
        ProviderType.GOOGLE,
        _build_google_genai_provider_with_info,
    )
