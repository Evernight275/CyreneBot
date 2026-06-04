from typing import Any, cast

from openai import AsyncOpenAI

from cyreneAI.core.errors.provider import ProviderConfigurationError
from cyreneAI.core.schema.chat import ChatRequest, ChatResponse
from cyreneAI.core.schema.image import ImageGenerationRequest, ImageGenerationResponse
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderModel
from cyreneAI.infra.adapters.providers.model_mapper import map_provider_model
from cyreneAI.infra.adapters.providers.openai_responses.errors import raise_openai_error
from cyreneAI.infra.adapters.providers.openai_responses.mapper import (
    map_image_generation_request,
    map_image_generation_response,
    map_responses_request,
    map_responses_response,
)


class OpenAIResponsesProviderInstance:
    def __init__(
        self,
        config: ProviderConfig,
        info: ProviderInfo,
        client: Any | None = None,
    ) -> None:
        if not config.api_key:
            raise ProviderConfigurationError(
                "openai-responses provider 必需提供api_key"
            )

        self.config = config
        self.info = info
        self.timeout = config.timeout.total_seconds() if config.timeout else None
        self._client = client or AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=self.timeout,
        )

    async def close(self) -> None:
        await self._client.close()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        try:
            payload = map_responses_request(request)
            response = cast(Any, await self._client.responses.create(**payload))
            return map_responses_response(
                provider_id=self.config.provider_id,
                response=response,
            )
        except Exception as exc:
            raise_openai_error(exc)

    async def list_models(self) -> list[ProviderModel]:
        try:
            response = await self._client.models.list()
            return [
                model
                for model in (map_provider_model(item) for item in response.data)
                if model is not None
            ]
        except Exception as exc:
            raise_openai_error(exc)

    async def generate_image(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResponse:
        try:
            payload = map_image_generation_request(request)
            response = cast(Any, await self._client.images.generate(**payload))
            return map_image_generation_response(
                provider_id=self.config.provider_id,
                model=request.model,
                response=response,
            )
        except Exception as exc:
            raise_openai_error(exc)
