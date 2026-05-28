from __future__ import annotations

from typing import cast

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import UnsupportedError
from cyreneAI.core.provider.provider_protocol import ImageGenerationProviderProtocol
from cyreneAI.core.schema.application import (
    ApplicationImageGenerationRequest,
    ApplicationImageGenerationResult,
)
from cyreneAI.core.schema.image import (
    ImageGenerationRequest,
)


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
