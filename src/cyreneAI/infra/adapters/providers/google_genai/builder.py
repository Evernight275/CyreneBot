from cyreneAI.core.provider.provider_protocol import ProviderInstanceProtocol
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo
from cyreneAI.infra.adapters.providers.google_genai.instance import (
    GoogleGenAIProviderInstance,
)


async def build_google_genai_provider(
    config: ProviderConfig,
    info: ProviderInfo,
) -> ProviderInstanceProtocol:
    return GoogleGenAIProviderInstance(
        config=config,
        info=info,
    )
