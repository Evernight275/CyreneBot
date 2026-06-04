from cyreneAI.core.provider.provider_protocol import ProviderInstanceProtocol
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo
from cyreneAI.infra.adapters.providers.openai_compatible.instance import (
    OpenAICompatibleProviderInstance,
)


async def build_openai_compatible_provider(
    config: ProviderConfig,
    info: ProviderInfo,
) -> ProviderInstanceProtocol:
    return OpenAICompatibleProviderInstance(
        config=config,
        info=info,
    )
