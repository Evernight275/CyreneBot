from typing import Any

from anthropic import AsyncAnthropic

from cyreneAI.core.errors.provider import ProviderConfigurationError
from cyreneAI.core.schema.chat import ChatRequest, ChatResponse
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderModel
from cyreneAI.infra.adapters.providers.anthropic.errors import raise_anthropic_error
from cyreneAI.infra.adapters.providers.anthropic.mapper import (
    map_anthropic_request,
    map_anthropic_response,
)
from cyreneAI.infra.adapters.providers.model_mapper import map_provider_model


class AnthropicProviderInstance:
    def __init__(
        self,
        config: ProviderConfig,
        info: ProviderInfo,
        client: Any | None = None,
    ) -> None:
        if not config.api_key:
            raise ProviderConfigurationError("anthropic provider 必需提供api_key")

        self.config = config
        self.info = info
        self.timeout = config.timeout.total_seconds() if config.timeout else None
        self._client = client or AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=self.timeout,
        )

    async def close(self) -> None:
        await self._client.close()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        try:
            payload = map_anthropic_request(request)
            response = await self._client.messages.create(**payload)
            return map_anthropic_response(
                provider_id=self.config.provider_id,
                response=response,
            )
        except Exception as exc:
            raise_anthropic_error(exc)

    async def list_models(self) -> list[ProviderModel]:
        try:
            response = await self._client.models.list()
            return [
                model
                for model in (map_provider_model(item) for item in response.data)
                if model is not None
            ]
        except Exception as exc:
            raise_anthropic_error(exc)
