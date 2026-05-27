from cyreneAI.core.provider.provider_protocol import ProviderInstanceProtocol
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo
from cyreneAI.infra.adapters.providers.anthropic.instance import (
    AnthropicProviderInstance,
)


async def build_anthropic_provider(
    config: ProviderConfig,
    info: ProviderInfo,
) -> ProviderInstanceProtocol:
    return AnthropicProviderInstance(
        config=config,
        info=info,
    )
