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
    IMAGE_GENERATION = "image_generation"
    VIDEO = "video"


class ProviderFeature(StrEnum):
    """
    提供商功能schema
    """

    TOOL_CALLING = "tool_calling"
    STREAMING = "streaming"
    VISION = "vision"
    JSON_MODE = "json_mode"
    MODEL_LISTING = "model_listing"


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


class ProviderModel(ProviderBase):
    """
    provider 模型信息schema
    """

    model_id: str
    name: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


def _empty_provider_models() -> list[ProviderModel]:
    return []


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


class ProviderConfigSummary(ProviderBase):
    """
    对外展示用 provider 配置摘要，不包含密钥明文。
    """

    provider_id: str
    provider_type: ProviderType
    has_api_key: bool = False
    base_url: str | None = None
    timeout: timedelta | None = None
    enabled: bool = True
    metadata: dict[str, str] = Field(default_factory=dict)


class ProviderAdminStatus(ProviderBase):
    """
    provider admin 视角的配置与运行状态。
    """

    provider_id: str
    provider_type: ProviderType | None = None
    configured: bool = False
    running: bool = False
    enabled: bool = False
    info: ProviderInfo | None = None
    config: ProviderConfigSummary | None = None


class ProviderOperationResult(ProviderBase):
    """
    provider admin 操作结果。
    """

    action: str
    provider_id: str
    accepted: bool = True
    detail: str | None = None
    status: ProviderAdminStatus | None = None


class ProviderConnectionCheckResult(ProviderBase):
    """
    provider 连通性检查结果。
    """

    provider_id: str
    ok: bool
    detail: str | None = None
    models: list[ProviderModel] = Field(default_factory=_empty_provider_models)
