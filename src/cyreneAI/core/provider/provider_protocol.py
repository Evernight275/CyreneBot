from typing import Protocol
from cyreneAI.core.schema.provider import ProviderInfo, ProviderConfig, ProviderModel
from cyreneAI.core.schema.chat import ChatRequest, ChatResponse
from cyreneAI.core.schema.embedding import EmbeddingRequest, EmbeddingResponse
from cyreneAI.core.schema.image import ImageGenerationRequest, ImageGenerationResponse


class ProviderInstanceProtocol(Protocol):
    """
    provider 实例协议
    """

    info: ProviderInfo
    config: ProviderConfig

    async def close(self) -> None:
        """
        关闭 provider 实例
        """
        ...


class ProviderFactoryProtocol(Protocol):
    async def create(self, config: ProviderConfig) -> ProviderInstanceProtocol:
        """
        创建 provider 实例
        """
        ...


class ProviderConfigStoreProtocol(Protocol):
    async def list_configs(self) -> list[ProviderConfig]:
        """
        列出已保存 provider 配置。
        """
        ...

    async def get_config(self, provider_id: str) -> ProviderConfig:
        """
        获取已保存 provider 配置。
        """
        ...

    async def upsert_config(self, config: ProviderConfig) -> ProviderConfig:
        """
        新增或更新 provider 配置。
        """
        ...

    async def delete_config(self, provider_id: str) -> None:
        """
        删除已保存 provider 配置。
        """
        ...

    async def close(self) -> None:
        """
        关闭配置存储。
        """
        ...


class ChatProviderProtocol(ProviderInstanceProtocol, Protocol):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """
        调用 provider 进行聊天
        """
        ...


class EmbeddingProviderProtocol(ProviderInstanceProtocol, Protocol):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """
        调用 provider 进行文本嵌入。
        """
        ...


class ModelListingProviderProtocol(ProviderInstanceProtocol, Protocol):
    async def list_models(self) -> list[ProviderModel]:
        """
        列出 provider 可用模型。
        """
        ...


class TTSProviderProtocol(ProviderInstanceProtocol, Protocol):
    async def tts(self, text: str) -> bytes:
        """
        调用 provider 进行文本转语音
        """
        ...


class ImageGenerationProviderProtocol(ProviderInstanceProtocol, Protocol):
    async def generate_image(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResponse:
        """
        调用 provider 生成图片。
        """
        ...
