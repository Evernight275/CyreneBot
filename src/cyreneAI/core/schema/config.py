from __future__ import annotations

from pydantic import Field

from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.provider import ProviderType


class ConfigProvider(CyreneAISchema):
    """
    Runtime provider configuration loaded from an external config file.
    """

    provider_id: str | None = None
    provider_type: ProviderType | None = None
    type: ProviderType | None = None
    api_key: str | None = Field(default=None, repr=False)
    api_key_env: str | None = None
    base_url: str | None = None
    model: str | None = None
    models: list[str] = Field(default_factory=list)
    timeout_seconds: float | None = Field(default=None, ge=0)
    enabled: bool = True
    metadata: dict[str, str] = Field(default_factory=dict)


class RuntimeConfig(CyreneAISchema):
    """
    Runtime configuration loaded from an external config file.
    """

    providers: dict[str, ConfigProvider] = Field(default_factory=dict)
