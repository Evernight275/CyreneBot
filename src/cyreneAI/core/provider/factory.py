from __future__ import annotations

from collections.abc import Awaitable, Callable

from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.provider import (
    ProviderNotFoundError,
)
from cyreneAI.core.provider.provider_protocol import ProviderInstanceProtocol
from cyreneAI.core.schema.provider import ProviderConfig, ProviderType

ProviderBuilder = Callable[[ProviderConfig], Awaitable[ProviderInstanceProtocol]]


class ProviderFactory:
    """
    Provider 工厂
    """

    def __init__(self) -> None:
        self._builders: dict[ProviderType, ProviderBuilder] = {}

    def register(self, provider_type: ProviderType, builder: ProviderBuilder) -> None:
        """
        注册 provider 构建器
        """
        if provider_type in self._builders:
            raise ConflictError(f"该提供商 {provider_type} 已注册")
        self._builders[provider_type] = builder

    def unregister(self, provider_type: ProviderType) -> None:
        """
        取消注册 provider 构建器
        :param provider_type: 提供商类型
        """
        builder = self._builders.get(provider_type)
        if builder is None:
            raise ProviderNotFoundError(f"该提供商 {provider_type} 未注册")
        self._builders.pop(provider_type, None)

    async def create(self, config: ProviderConfig) -> ProviderInstanceProtocol:
        """
        创建 provider 实例
        """
        builder = self._builders.get(config.provider_type)
        if builder is None:
            raise ProviderNotFoundError(f"该提供商 {config.provider_type} 未注册")
        return await builder(config)

    def exists(self, provider_type: ProviderType) -> bool:
        """
        检查 provider 是否已注册
        :param provider_type: 提供商类型
        :return: 是否已注册
        """
        return provider_type in self._builders
