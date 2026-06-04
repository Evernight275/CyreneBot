from __future__ import annotations

from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.provider import (
    ProviderNotFoundError,
)
from cyreneAI.core.schema.provider import (
    ProviderCapability,
    ProviderInfo,
    ProviderType,
)


class ProviderRegistry:
    """
    提供商注册器
    """

    def __init__(self):
        self._providers: dict[ProviderType, ProviderInfo] = {}

    def register_provider(self, provider: ProviderInfo):
        """
        注册提供商
        """
        if provider.provider_type in self._providers:
            raise ConflictError(f"该提供商 {provider.provider_type} 已注册")
        self._providers[provider.provider_type] = provider

    def get(self, provider_type: ProviderType) -> ProviderInfo:
        """
        获取提供商
        """
        if provider_type not in self._providers:
            raise ProviderNotFoundError(f"该提供商 {provider_type} 不存在")
        return self._providers[provider_type]

    def unregister_provider(self, provider_type: ProviderType):
        """
        注销提供商
        :param provider_type: 提供商类型
        """
        if provider_type not in self._providers:
            raise ProviderNotFoundError(f"该提供商 {provider_type} 不存在")
        del self._providers[provider_type]

    def exists(self, provider_type: ProviderType) -> bool:
        """
        检查提供商是否存在
        :param provider_id: 提供商id
        :return: 是否存在提供商
        """
        return provider_type in self._providers

    def get_all(self) -> list[ProviderInfo]:
        """
        获取所有提供商
        """
        return list(self._providers.values())

    def list_by_capability(
        self,
        capability: ProviderCapability,
    ) -> list[ProviderInfo]:
        """
        按 provider 能力筛选。
        """
        return [
            provider
            for provider in self._providers.values()
            if provider.capabilities and capability in provider.capabilities
        ]
