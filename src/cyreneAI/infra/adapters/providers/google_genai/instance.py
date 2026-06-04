import asyncio
from typing import Any

from google import genai
from google.genai.types import HttpOptionsDict

from cyreneAI.core.errors.provider import ProviderConfigurationError
from cyreneAI.core.schema.chat import ChatRequest, ChatResponse
from cyreneAI.core.schema.image import ImageGenerationRequest, ImageGenerationResponse
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderModel
from cyreneAI.infra.adapters.providers.google_genai.errors import (
    raise_google_genai_error,
)
from cyreneAI.infra.adapters.providers.google_genai.mapper import (
    map_google_content_image_generation_request,
    map_google_content_image_generation_response,
    map_google_genai_request,
    map_google_genai_response,
    map_google_image_generation_request,
    map_google_image_generation_response,
    should_use_google_generate_images,
)
from cyreneAI.infra.adapters.providers.model_mapper import map_provider_model


class GoogleGenAIProviderInstance:
    def __init__(
        self,
        config: ProviderConfig,
        info: ProviderInfo,
        client: Any | None = None,
    ) -> None:
        if not config.api_key:
            raise ProviderConfigurationError("google-genai provider 必需提供api_key")

        self.config = config
        self.info = info
        self.timeout = config.timeout.total_seconds() if config.timeout else None
        http_options: HttpOptionsDict | None = None
        if config.base_url is not None or self.timeout is not None:
            http_options = {}
            if config.base_url is not None:
                http_options["base_url"] = config.base_url
            if self.timeout is not None:
                http_options["timeout"] = int(self.timeout * 1000)
        self._client = client or genai.Client(
            api_key=config.api_key,
            http_options=http_options,
        )

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

    async def chat(self, request: ChatRequest) -> ChatResponse:
        try:
            payload = map_google_genai_request(request)
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                **payload,
            )
            return map_google_genai_response(
                provider_id=self.config.provider_id,
                response=response,
            )
        except Exception as exc:
            raise_google_genai_error(exc)

    async def list_models(self) -> list[ProviderModel]:
        try:
            response = await asyncio.to_thread(self._client.models.list)
            return [
                model
                for model in (map_provider_model(item) for item in response)
                if model is not None
            ]
        except Exception as exc:
            raise_google_genai_error(exc)

    async def generate_image(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResponse:
        try:
            if should_use_google_generate_images(request):
                payload = map_google_image_generation_request(request)
                response = await asyncio.to_thread(
                    self._client.models.generate_images,
                    **payload,
                )
                return map_google_image_generation_response(
                    provider_id=self.config.provider_id,
                    model=request.model,
                    response=response,
                )

            payload = map_google_content_image_generation_request(request)
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                **payload,
            )
            return map_google_content_image_generation_response(
                provider_id=self.config.provider_id,
                model=request.model,
                response=response,
            )
        except Exception as exc:
            raise_google_genai_error(exc)
