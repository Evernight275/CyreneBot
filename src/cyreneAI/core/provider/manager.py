from __future__ import annotations

from cyreneAI.core.errors.base import ConflictError, NotFoundError, StateError
from cyreneAI.core.provider.provider_protocol import (
    ProviderFactoryProtocol,
    ProviderInstanceProtocol,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderModel


class ProviderManager:
    """
    Provider 运行时管理器。

    只负责 provider 实例生命周期：
    1. 创建
    2. 获取
    3. 移除
    4. 重载
    5. 关闭
    """

    def __init__(self, factory: ProviderFactoryProtocol) -> None:
        self._factory = factory
        self._instances: dict[str, ProviderInstanceProtocol] = {}

    async def add(self, config: ProviderConfig) -> ProviderInstanceProtocol:
        """
        根据配置创建并加入 provider 实例。
        """

        provider_id = config.provider_id

        if provider_id in self._instances:
            raise ConflictError(f"Provider instance already exists: {provider_id}")

        instance = await self._factory.create(config)
        self._instances[provider_id] = instance

        return instance

    def get(self, provider_id: str) -> ProviderInstanceProtocol:
        """
        获取 provider 实例。
        """

        instance = self._instances.get(provider_id)

        if instance is None:
            raise NotFoundError(f"Provider instance not found: {provider_id}")

        return instance

    def exists(self, provider_id: str) -> bool:
        """
        判断 provider 实例是否存在。
        """

        return provider_id in self._instances

    def list_running(self) -> list[ProviderInfo]:
        """
        列出当前运行中的 provider 信息。
        """

        return [instance.info for instance in self._instances.values()]

    def list_running_ids(self) -> list[str]:
        """
        列出当前运行中的 provider id。
        """

        return list(self._instances.keys())

    def list_running_configs(self) -> list[ProviderConfig]:
        """
        列出当前运行中的 provider 配置。
        """

        return [instance.config for instance in self._instances.values()]

    async def list_models(self, provider_id: str) -> list[ProviderModel]:
        """
        列出 provider 可用模型。

        如果运行时 provider 不支持实时列模型，或实时返回空列表，则回退到
        provider config 中声明的自定义模型，再回退到 provider catalog 中声明的
        静态模型列表。

        实时请求失败必须继续向上抛出，避免把错误 base_url、错误路径或鉴权
        失败伪装成“配置模型可用”。
        """

        instance = self.get(provider_id)
        list_models = getattr(instance, "list_models", None)
        if list_models is not None:
            models = _deduplicate_models(await list_models())
            if models:
                return models

        return _fallback_models(instance)

    async def remove(self, provider_id: str) -> None:
        """
        移除并关闭 provider 实例。
        """

        instance = self._instances.pop(provider_id, None)

        if instance is None:
            raise NotFoundError(f"Provider instance not found: {provider_id}")

        await instance.close()

    async def reload(self, config: ProviderConfig) -> ProviderInstanceProtocol:
        """
        重新加载 provider 实例。

        成功创建新实例后，再关闭旧实例，避免 reload 失败导致原实例丢失。
        """

        provider_id = config.provider_id
        old_instance = self._instances.get(provider_id)

        new_instance = await self._factory.create(config)
        self._instances[provider_id] = new_instance

        if old_instance is not None:
            await old_instance.close()

        return new_instance

    async def close_all(self) -> None:
        """
        关闭全部 provider 实例。
        """

        errors: list[Exception] = []

        for provider_id, instance in list(self._instances.items()):
            try:
                await instance.close()
            except Exception as exc:
                errors.append(exc)
            finally:
                self._instances.pop(provider_id, None)

        if errors:
            raise StateError(
                f"Failed to close {len(errors)} provider instance(s)",
                cause=errors[0],
            )


def _catalog_models(info: ProviderInfo) -> list[ProviderModel]:
    return _deduplicate_models(
        [ProviderModel(model_id=model_id) for model_id in (info.models or [])]
    )


def _fallback_models(instance: ProviderInstanceProtocol) -> list[ProviderModel]:
    config_models = _config_models(instance.config)
    if config_models:
        return config_models
    return _catalog_models(instance.info)


def _config_models(config: ProviderConfig) -> list[ProviderModel]:
    models = list(config.models)
    metadata_model = config.metadata.get("model")
    if metadata_model:
        models.append(ProviderModel(model_id=metadata_model))
    return _deduplicate_models(models)


def _deduplicate_models(models: list[ProviderModel]) -> list[ProviderModel]:
    result: list[ProviderModel] = []
    seen: set[str] = set()
    for model in models:
        model_id = model.model_id.strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        result.append(model.model_copy(update={"model_id": model_id}))
    return result
