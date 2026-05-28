from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import Field

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import UnsupportedError
from cyreneAI.core.provider.provider_protocol import ImageGenerationProviderProtocol
from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.image import (
    ImageGenerationRequest,
    ImageGenerationResponse,
)


class ApplicationImageGenerationRequest(CyreneAISchema):
    """
    应用图片生成请求
    """

    provider_id: str
    model: str
    prompt: str
    count: int = Field(default=1, ge=1)
    size: str | None = None
    quality: str | None = None
    response_format: Literal["url", "b64_json"] = "b64_json"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationImageGenerationResult(CyreneAISchema):
    """
    应用图片生成结果
    """

    response: ImageGenerationResponse
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageGenerationOrchestrator:
    """
    应用图片生成编排器
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._runtime = runtime

    async def generate_image(
        self,
        request: ApplicationImageGenerationRequest,
    ) -> ApplicationImageGenerationResult:
        provider_request = ImageGenerationRequest(
            provider_id=request.provider_id,
            model=request.model,
            prompt=request.prompt,
            count=request.count,
            size=request.size,
            quality=request.quality,
            response_format=request.response_format,
            metadata=request.metadata.copy(),
        )
        provider = self._get_image_generation_provider(request.provider_id)
        response = await provider.generate_image(provider_request)
        return ApplicationImageGenerationResult(
            response=response,
            metadata={
                **request.metadata,
                "image_count": len(response.images),
            },
        )

    def _get_image_generation_provider(
        self,
        provider_id: str,
    ) -> ImageGenerationProviderProtocol:
        provider = self._runtime.provider_manager.get(provider_id)
        generate_image = getattr(provider, "generate_image", None)
        if generate_image is None:
            raise UnsupportedError(
                f"Provider {provider_id} does not support image generation"
            )
        return cast(ImageGenerationProviderProtocol, provider)
