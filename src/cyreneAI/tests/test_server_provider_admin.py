from __future__ import annotations

import asyncio

import pytest

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.errors.base import NotFoundError, StateError
from cyreneAI.core.errors.provider import ProviderUnavailableError
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.provider import (
    ProviderConfig,
    ProviderInfo,
    ProviderModel,
    ProviderType,
)
from cyreneAI.server.provider_admin import ProviderAdminService


def _config(
    provider_id: str = "provider-1",
    *,
    provider_type: ProviderType = ProviderType.OPENAI_COMPATIBLE,
    enabled: bool = True,
    api_key: str | None = "test-key",
) -> ProviderConfig:
    return ProviderConfig(
        provider_id=provider_id,
        provider_type=provider_type,
        enabled=enabled,
        api_key=api_key,
    )


def _info(provider_type: ProviderType = ProviderType.OPENAI_COMPATIBLE) -> ProviderInfo:
    return ProviderInfo(
        provider_type=provider_type,
        name=f"{provider_type} provider",
        description="test provider",
        models=["catalog-model"],
    )


class _FakeProviderInstance:
    def __init__(
        self,
        config: ProviderConfig,
        *,
        list_error: Exception | None = None,
    ) -> None:
        self.config = config
        self.info = _info(config.provider_type)
        self.closed = False
        self.list_error = list_error

    async def close(self) -> None:
        self.closed = True

    async def list_models(self) -> list[ProviderModel]:
        if self.list_error is not None:
            raise self.list_error
        return [ProviderModel(model_id="runtime-model")]


class _RecordingProviderFactory:
    def __init__(self) -> None:
        self.instances: list[_FakeProviderInstance] = []
        self.next_list_error: Exception | None = None

    async def create(self, config: ProviderConfig) -> _FakeProviderInstance:
        instance = _FakeProviderInstance(config, list_error=self.next_list_error)
        self.instances.append(instance)
        return instance


class _MemoryProviderConfigStore:
    def __init__(self, *configs: ProviderConfig) -> None:
        self.configs = {config.provider_id: config for config in configs}
        self.closed = False

    async def list_configs(self) -> list[ProviderConfig]:
        return list(self.configs.values())

    async def get_config(self, provider_id: str) -> ProviderConfig:
        config = self.configs.get(provider_id)
        if config is None:
            raise NotFoundError(f"Provider config not found: {provider_id}")
        return config

    async def upsert_config(self, config: ProviderConfig) -> ProviderConfig:
        self.configs[config.provider_id] = config
        return config

    async def delete_config(self, provider_id: str) -> None:
        self.configs.pop(provider_id, None)

    async def close(self) -> None:
        self.closed = True


def _provider_manager(
    recording_factory: _RecordingProviderFactory | None = None,
) -> ProviderManager:
    recording_factory = recording_factory or _RecordingProviderFactory()
    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI_COMPATIBLE, recording_factory.create)
    return ProviderManager(factory)


def _registry(*provider_types: ProviderType) -> ProviderRegistry:
    registry = ProviderRegistry()
    for provider_type in provider_types:
        registry.register_provider(_info(provider_type))
    return registry


def _runtime(
    *,
    provider_manager: ProviderManager | None = None,
    provider_registry: ProviderRegistry | None = None,
    provider_config_store: _MemoryProviderConfigStore | None = None,
) -> CyreneAIRuntime:
    return CyreneAIRuntime(
        provider_manager=provider_manager or _provider_manager(),
        provider_registry=provider_registry,
        provider_config_store=provider_config_store,
        context_builder=ContextWindowBuilder(),
    )


def test_provider_admin_requires_registry_and_config_store() -> None:
    async def run() -> None:
        service = ProviderAdminService(_runtime())

        with pytest.raises(StateError, match="Provider registry is not configured"):
            service.list_catalog()

        with pytest.raises(StateError, match="Provider config store is not configured"):
            await service.list_configs()

    asyncio.run(run())


def test_provider_admin_lists_running_and_saved_statuses() -> None:
    async def run() -> None:
        provider_manager = _provider_manager()
        await provider_manager.add(_config("running"))
        store = _MemoryProviderConfigStore(
            _config("saved", enabled=False, api_key=None),
        )
        service = ProviderAdminService(
            _runtime(
                provider_manager=provider_manager,
                provider_registry=_registry(ProviderType.OPENAI_COMPATIBLE),
                provider_config_store=store,
            )
        )

        statuses = await service.list_statuses()

        assert [status.provider_id for status in statuses] == ["running", "saved"]
        assert statuses[0].configured is False
        assert statuses[0].running is True
        assert statuses[0].enabled is True
        assert statuses[0].info is provider_manager.get("running").info
        assert statuses[1].configured is True
        assert statuses[1].running is False
        assert statuses[1].enabled is False
        assert statuses[1].info == _info(ProviderType.OPENAI_COMPATIBLE)
        assert statuses[1].config is not None
        assert statuses[1].config.has_api_key is False

    asyncio.run(run())


def test_provider_admin_inspect_reports_missing_provider() -> None:
    async def run() -> None:
        service = ProviderAdminService(_runtime(provider_config_store=None))

        with pytest.raises(NotFoundError, match="Provider not found: missing"):
            await service.inspect("missing")

    asyncio.run(run())


def test_provider_admin_status_omits_catalog_info_when_registry_missing_entry() -> None:
    async def run() -> None:
        service = ProviderAdminService(
            _runtime(
                provider_registry=_registry(),
                provider_config_store=_MemoryProviderConfigStore(
                    _config(
                        "saved",
                        provider_type=ProviderType.VLLM,
                        enabled=False,
                    )
                ),
            )
        )

        status = await service.inspect("saved")

        assert status.provider_type == ProviderType.VLLM
        assert status.info is None
        assert status.config is not None
        assert status.config.provider_type == ProviderType.VLLM

    asyncio.run(run())


def test_provider_admin_upsert_validates_path_and_removes_disabled_running_provider() -> None:
    async def run() -> None:
        provider_manager = _provider_manager()
        await provider_manager.add(_config("provider-1"))
        store = _MemoryProviderConfigStore()
        service = ProviderAdminService(
            _runtime(
                provider_manager=provider_manager,
                provider_registry=_registry(ProviderType.OPENAI_COMPATIBLE),
                provider_config_store=store,
            )
        )

        with pytest.raises(StateError, match="provider_id must match"):
            await service.upsert_config("provider-1", _config("other-provider"))

        status = await service.upsert_config(
            "provider-1",
            _config("provider-1", enabled=False),
        )
        inactive_status = await service.upsert_config(
            "new-disabled",
            _config("new-disabled", enabled=False),
        )

        assert provider_manager.exists("provider-1") is False
        assert status.config is not None
        assert status.config.enabled is False
        assert store.configs["provider-1"].enabled is False
        assert inactive_status.config is not None
        assert inactive_status.config.enabled is False

    asyncio.run(run())


def test_provider_admin_upsert_reloads_existing_enabled_provider() -> None:
    async def run() -> None:
        recording_factory = _RecordingProviderFactory()
        provider_manager = _provider_manager(recording_factory)
        await provider_manager.add(_config("provider-1"))
        old_instance = recording_factory.instances[0]
        store = _MemoryProviderConfigStore()
        service = ProviderAdminService(
            _runtime(
                provider_manager=provider_manager,
                provider_registry=_registry(ProviderType.OPENAI_COMPATIBLE),
                provider_config_store=store,
            )
        )
        updated = _config("provider-1").model_copy(
            update={"metadata": {"revision": "2"}}
        )

        status = await service.upsert_config("provider-1", updated)

        assert old_instance.closed is True
        assert provider_manager.get("provider-1").config.metadata == {"revision": "2"}
        assert store.configs["provider-1"].metadata == {"revision": "2"}
        assert status.running is True
        assert status.config is not None
        assert status.config.metadata == {"revision": "2"}

    asyncio.run(run())


def test_provider_admin_stop_persists_disabled_config_and_reports_missing_provider() -> None:
    async def run() -> None:
        provider_manager = _provider_manager()
        store = _MemoryProviderConfigStore(_config("saved"))
        service = ProviderAdminService(
            _runtime(provider_manager=provider_manager, provider_config_store=store)
        )

        stopped = await service.stop("saved")

        assert stopped.action == "stop"
        assert store.configs["saved"].enabled is False
        assert stopped.status is not None
        assert stopped.status.enabled is False

        with pytest.raises(NotFoundError, match="Provider not found: missing"):
            await service.stop("missing")

    asyncio.run(run())


def test_provider_admin_reload_uses_running_config_when_no_saved_config() -> None:
    async def run() -> None:
        recording_factory = _RecordingProviderFactory()
        provider_manager = _provider_manager(recording_factory)
        await provider_manager.add(_config("provider-1"))
        service = ProviderAdminService(
            _runtime(
                provider_manager=provider_manager,
                provider_config_store=_MemoryProviderConfigStore(),
            )
        )

        result = await service.reload("provider-1")

        assert result.action == "reload"
        assert result.status is not None
        assert result.status.running is True
        assert len(recording_factory.instances) == 2

        with pytest.raises(NotFoundError, match="Provider not found: missing"):
            await service.reload("missing")

    asyncio.run(run())


def test_provider_admin_check_returns_provider_errors_as_failed_result() -> None:
    async def run() -> None:
        recording_factory = _RecordingProviderFactory()
        recording_factory.next_list_error = ProviderUnavailableError("provider down")
        provider_manager = _provider_manager(recording_factory)
        await provider_manager.add(_config("provider-1"))
        service = ProviderAdminService(_runtime(provider_manager=provider_manager))

        result = await service.check("provider-1")

        assert result.ok is False
        assert result.detail == "provider down"
        assert result.models == []

    asyncio.run(run())
