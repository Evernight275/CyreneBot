from __future__ import annotations

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import NotFoundError, StateError
from cyreneAI.core.errors.provider import ProviderError
from cyreneAI.core.schema.provider import (
    ProviderAdminStatus,
    ProviderConfig,
    ProviderConfigSummary,
    ProviderConnectionCheckResult,
    ProviderInfo,
    ProviderOperationResult,
    ProviderType,
)


class ProviderAdminService:
    """
    Server 层 provider 管理用例编排。
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._runtime = runtime

    def list_catalog(self) -> list[ProviderInfo]:
        registry = self._provider_registry()
        return registry.get_all()

    async def list_configs(self) -> list[ProviderConfigSummary]:
        store = self._provider_config_store()
        return [_config_summary(config) for config in await store.list_configs()]

    async def list_statuses(self) -> list[ProviderAdminStatus]:
        provider_ids = set(self._runtime.provider_manager.list_running_ids())
        store = self._runtime.provider_config_store
        configs: dict[str, ProviderConfig] = {}
        if store is not None:
            configs = {
                config.provider_id: config for config in await store.list_configs()
            }
            provider_ids.update(configs)

        return [
            self._build_status(provider_id, saved_config=configs.get(provider_id))
            for provider_id in sorted(provider_ids)
        ]

    async def inspect(self, provider_id: str) -> ProviderAdminStatus:
        saved_config = await self._get_saved_config_or_none(provider_id)
        if saved_config is None and not self._runtime.provider_manager.exists(
            provider_id
        ):
            raise NotFoundError(f"Provider not found: {provider_id}")
        return self._build_status(provider_id, saved_config=saved_config)

    async def upsert_config(
        self,
        provider_id: str,
        config: ProviderConfig,
    ) -> ProviderAdminStatus:
        if config.provider_id != provider_id:
            raise StateError("Provider config provider_id must match path provider_id")
        store = self._provider_config_store()
        if config.enabled:
            await self._reload_or_add(config)
            saved = await store.upsert_config(config)
        elif self._runtime.provider_manager.exists(provider_id):
            await self._runtime.provider_manager.remove(provider_id)
            saved = await store.upsert_config(config)
        else:
            saved = await store.upsert_config(config)
        return self._build_status(provider_id, saved_config=saved)

    async def delete_config(self, provider_id: str) -> ProviderOperationResult:
        store = self._provider_config_store()
        await store.delete_config(provider_id)
        if self._runtime.provider_manager.exists(provider_id):
            await self._runtime.provider_manager.remove(provider_id)
        return ProviderOperationResult(
            action="delete_config",
            provider_id=provider_id,
            detail=f"Provider config deleted: {provider_id}",
            status=self._build_status(provider_id),
        )

    async def start(self, provider_id: str) -> ProviderOperationResult:
        store = self._provider_config_store()
        config = await store.get_config(provider_id)
        config = config.model_copy(update={"enabled": True})
        await self._reload_or_add(config)
        await store.upsert_config(config)
        return ProviderOperationResult(
            action="start",
            provider_id=provider_id,
            detail=f"Provider started: {provider_id}",
            status=self._build_status(provider_id, saved_config=config),
        )

    async def stop(self, provider_id: str) -> ProviderOperationResult:
        saved_config = await self._get_saved_config_or_none(provider_id)
        if saved_config is not None and self._runtime.provider_config_store is not None:
            saved_config = saved_config.model_copy(update={"enabled": False})
            await self._runtime.provider_config_store.upsert_config(saved_config)

        if self._runtime.provider_manager.exists(provider_id):
            await self._runtime.provider_manager.remove(provider_id)
        elif saved_config is None:
            raise NotFoundError(f"Provider not found: {provider_id}")

        return ProviderOperationResult(
            action="stop",
            provider_id=provider_id,
            detail=f"Provider stopped: {provider_id}",
            status=self._build_status(provider_id, saved_config=saved_config),
        )

    async def reload(self, provider_id: str) -> ProviderOperationResult:
        config = await self._get_saved_config_or_none(provider_id)
        if config is None:
            if not self._runtime.provider_manager.exists(provider_id):
                raise NotFoundError(f"Provider not found: {provider_id}")
            config = self._runtime.provider_manager.get(provider_id).config
        await self._runtime.provider_manager.reload(config)
        return ProviderOperationResult(
            action="reload",
            provider_id=provider_id,
            detail=f"Provider reloaded: {provider_id}",
            status=self._build_status(provider_id, saved_config=config),
        )

    async def check(self, provider_id: str) -> ProviderConnectionCheckResult:
        try:
            models = await self._runtime.provider_manager.list_models(provider_id)
        except ProviderError as exc:
            return ProviderConnectionCheckResult(
                provider_id=provider_id,
                ok=False,
                detail=str(exc),
            )
        return ProviderConnectionCheckResult(
            provider_id=provider_id,
            ok=True,
            detail=f"Provider {provider_id} is reachable.",
            models=models,
        )

    def _provider_registry(self):
        if self._runtime.provider_registry is None:
            raise StateError("Provider registry is not configured")
        return self._runtime.provider_registry

    def _provider_config_store(self):
        if self._runtime.provider_config_store is None:
            raise StateError("Provider config store is not configured")
        return self._runtime.provider_config_store

    async def _get_saved_config_or_none(
        self,
        provider_id: str,
    ) -> ProviderConfig | None:
        store = self._runtime.provider_config_store
        if store is None:
            return None
        try:
            return await store.get_config(provider_id)
        except NotFoundError:
            return None

    async def _reload_or_add(self, config: ProviderConfig) -> None:
        if self._runtime.provider_manager.exists(config.provider_id):
            await self._runtime.provider_manager.reload(config)
            return
        await self._runtime.provider_manager.add(config)

    def _build_status(
        self,
        provider_id: str,
        *,
        saved_config: ProviderConfig | None = None,
    ) -> ProviderAdminStatus:
        running = self._runtime.provider_manager.exists(provider_id)
        running_config = None
        info = None
        if running:
            instance = self._runtime.provider_manager.get(provider_id)
            running_config = instance.config
            info = instance.info

        display_config = saved_config or running_config
        provider_type = display_config.provider_type if display_config else None
        if info is None and provider_type is not None:
            info = self._catalog_info_or_none(provider_type)

        return ProviderAdminStatus(
            provider_id=provider_id,
            provider_type=provider_type,
            configured=saved_config is not None,
            running=running,
            enabled=display_config.enabled if display_config is not None else False,
            info=info,
            config=(
                _config_summary(display_config) if display_config is not None else None
            ),
        )

    def _catalog_info_or_none(self, provider_type: ProviderType) -> ProviderInfo | None:
        registry = self._runtime.provider_registry
        if registry is None:
            return None
        try:
            return registry.get(provider_type)
        except ProviderError:
            return None


def _config_summary(config: ProviderConfig) -> ProviderConfigSummary:
    return ProviderConfigSummary(
        provider_id=config.provider_id,
        provider_type=config.provider_type,
        has_api_key=config.api_key is not None,
        base_url=config.base_url,
        timeout=config.timeout,
        enabled=config.enabled,
        models=list(config.models),
        metadata=config.metadata.copy(),
    )


__all__ = ["ProviderAdminService"]
