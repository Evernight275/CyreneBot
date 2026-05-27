from __future__ import annotations

from cyreneAI.core.schema.provider import (
    ProviderCapability,
    ProviderFeature,
    ProviderInfo,
    ProviderType,
)

GOOGLE_GENAI_PROVIDER_INFO = ProviderInfo(
    provider_type=ProviderType.GOOGLE,
    name="Google GenAI",
    description="Provider registration for Google GenAI chat workflows.",
    models=None,
    capabilities=[
        ProviderCapability.CHAT,
    ],
    features=[
        ProviderFeature.TOOL_CALLING,
        ProviderFeature.STREAMING,
        ProviderFeature.JSON_MODE,
        ProviderFeature.MODEL_LISTING,
    ],
)
