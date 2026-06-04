from typing import Any, cast

from openai import AsyncOpenAI

from cyreneAI.core.errors.provider import ProviderConfigurationError
from cyreneAI.core.schema.chat import ChatRequest, ChatResponse
from cyreneAI.core.schema.embedding import EmbeddingRequest, EmbeddingResponse
from cyreneAI.core.schema.provider import (
    ProviderConfig,
    ProviderInfo,
    ProviderModel,
)
from cyreneAI.infra.adapters.providers.model_mapper import map_provider_model
from cyreneAI.infra.adapters.providers.openai_compatible.errors import (
    raise_openai_error,
)
from cyreneAI.infra.adapters.providers.openai_compatible.mapper import (
    map_chat_request,
    map_chat_response,
    map_embedding_request,
    map_embedding_response,
)


class OpenAICompatibleProviderInstance:
    def __init__(
        self,
        config: ProviderConfig,
        info: ProviderInfo,
        client: Any | None = None,
    ) -> None:
        if not config.api_key:
            raise ProviderConfigurationError(
                "openai-compatible provider 必需提供api_key"
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
            payload = map_chat_request(
                request,
                include_reasoning_content=_is_deepseek_provider(self.config),
            )
            response = cast(
                Any,
                await self._client.chat.completions.create(**payload),
            )
            return map_chat_response(
                provider_id=self.config.provider_id,
                response=response,
            )
        except Exception as exc:
            raise_openai_error(exc)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        try:
            payload = map_embedding_request(request)
            response: Any = await self._client.embeddings.create(**payload)
            return map_embedding_response(
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


def _is_deepseek_provider(config: ProviderConfig) -> bool:
    values: list[Any] = [
        config.provider_id,
        config.base_url,
        *config.metadata.keys(),
        *config.metadata.values(),
    ]
    return any(
        isinstance(value, str) and "deepseek" in value.casefold() for value in values
    )
