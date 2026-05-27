from __future__ import annotations

from enum import StrEnum
from pydantic import Field
from datetime import timedelta
from cyreneAI.core.schema.base import CyreneAISchema


class ProviderBase(CyreneAISchema):
    """
    所有与提供商有关的schema应该继承这个schema
    """

    pass


class ProviderCapability(StrEnum):
    """
    提供商能力schema
    """

    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    TTS = "tts"
    STT = "stt"
    SEARCH = "search"
    IMAGE = "image"
    VIDEO = "video"


class ProviderFeature(StrEnum):
    """
    提供商功能schema
    """

    TOOL_CALLING = "tool_calling"
    STREAMING = "streaming"
    VISION = "vision"
    JSON_MODE = "json_mode"


class ProviderType(StrEnum):
    """
    提供商类型schema
    """

    OPENAI_COMPATIBLE = "openai_compatible"
    OPENAI_RESPONSES = "openai_responses"
    OPENAI = "openai"
    GOOGLE = "google"
    ANTHROPIC = "anthropic"
    VLLM = "vllm"
    OLLAMA = "ollama"


class ProviderInfo(ProviderBase):
    """
    提供商信息schema
    """

    provider_type: ProviderType
    name: str
    description: str
    models: list[str] | None = None
    capabilities: list[ProviderCapability] | None = None
    features: list[ProviderFeature] | None = None


class ProviderReference(ProviderBase):
    """
    提供商引用schema
    """

    provider_id: str
    name: str


class ProviderConfig(ProviderBase):
    """
    提供商配置schema
    """

    provider_id: str
    provider_type: ProviderType
    api_key: str | None = Field(default=None, repr=False)
    base_url: str | None = None
    timeout: timedelta | None = Field(
        default=None, ge=timedelta(seconds=0), description="请求超时时间"
    )
    enabled: bool = True
    metadata: dict[str, str] = Field(default_factory=dict)
