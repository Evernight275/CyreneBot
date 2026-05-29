from __future__ import annotations

from cyreneAI.core.schema.provider import (
    ProviderCapability,
    ProviderFeature,
    ProviderInfo,
    ProviderType,
)

OPENAI_COMPATIBLE_PROVIDER_INFO = ProviderInfo(
    provider_type=ProviderType.OPENAI_COMPATIBLE,
    name="OpenAI Compatible",
    description="Provider registration for OpenAI-compatible chat completion APIs.",
    models=None,
    capabilities=[
        ProviderCapability.CHAT,
        ProviderCapability.EMBEDDING,
    ],
    features=[
        ProviderFeature.TOOL_CALLING,
        ProviderFeature.STREAMING,
        ProviderFeature.JSON_MODE,
        ProviderFeature.MODEL_LISTING,
    ],
)
