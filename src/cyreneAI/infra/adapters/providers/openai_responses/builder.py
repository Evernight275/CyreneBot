from cyreneAI.core.provider.provider_protocol import ProviderInstanceProtocol
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo
from cyreneAI.infra.adapters.providers.openai_responses.instance import (
    OpenAIResponsesProviderInstance,
)


async def build_openai_responses_provider(
    config: ProviderConfig,
    info: ProviderInfo,
) -> ProviderInstanceProtocol:
    return OpenAIResponsesProviderInstance(
        config=config,
        info=info,
    )
