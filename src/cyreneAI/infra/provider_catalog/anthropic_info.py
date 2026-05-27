from __future__ import annotations

from cyreneAI.core.schema.provider import (
    ProviderCapability,
    ProviderFeature,
    ProviderInfo,
    ProviderType,
)

ANTHROPIC_PROVIDER_INFO = ProviderInfo(
    provider_type=ProviderType.ANTHROPIC,
    name="Anthropic",
    description="Provider registration for Anthropic Messages API chat workflows.",
    models=None,
    capabilities=[
        ProviderCapability.CHAT,
    ],
    features=[
        ProviderFeature.TOOL_CALLING,
        ProviderFeature.STREAMING,
        ProviderFeature.MODEL_LISTING,
    ],
)
